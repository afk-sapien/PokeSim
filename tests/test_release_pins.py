"""A public release must not carry the temporary wheel pins, and its pins must agree with each other."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import finalize_release_pins  # noqa: E402
import release_pins  # noqa: E402

TEMP_BASE = 'https://raw.githubusercontent.com/example/PokeSim/refs/heads/release/9.9.9/tools/temp-wheels/'
FINAL_BASE = 'https://github.com/example/pyboy-rs/releases/download/v0.1.1/'
WHEEL = 'pyboy_rs-0.1.1-cp311-abi3-win_amd64.whl'
CORE = 'pokesim_core-0.2.0-py3-none-any.whl'
SDIST = 'pyboy_rs-0.1.1.tar.gz'
BLOBS = {WHEEL: b'wheel bytes', CORE: b'core bytes', SDIST: b'sdist bytes'}
HASHES = {name: hashlib.sha256(blob).hexdigest() for name, blob in BLOBS.items()}


def make_tree(root, base=TEMP_BASE, fragments=False, sdist_hash=None, temp_files=True):
    def url(name):
        return base + name + (('#sha256=' + HASHES[name]) if fragments else '')

    (root / 'pyproject.toml').write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\ndependencies = [\n'
        f'  "pokesim-core[emulator] @ {url(CORE)}",\n'
        f'  "pyboy-rs @ {url(WHEEL)} ; sys_platform == \'win32\'",\n]\n')
    lock = ''
    for name, package in ((CORE, 'pokesim-core'), (WHEEL, 'pyboy-rs')):
        version = '0.2.0' if package == 'pokesim-core' else '0.1.1'
        lock += (f'[[package]]\nname = "{package}"\nversion = "{version}"\nsource = {{ url = "{base + name}" }}\n'
                 f'wheels = [\n    {{ url = "{base + name}", hash = "sha256:{HASHES[name]}" }},\n]\n\n')
    (root / 'uv.lock').write_text(lock)
    (root / 'Dockerfile').write_text(
        f'ARG EMULATOR_SOURCE_URL={base + SDIST}\n'
        f'ARG EMULATOR_SOURCE_SHA256={HASHES[SDIST] if sdist_hash is None else sdist_hash}\n')
    if temp_files:
        (root / 'tools/temp-wheels').mkdir(parents=True)
        (root / 'tools/temp-wheels' / WHEEL).write_bytes(BLOBS[WHEEL])
        (root / 'TEMP_REMOVE_BEFORE_RELEASE.md').write_text('# TEMP\n')
    return root


def final_tree(root, **kwargs):
    (root / 'tools').mkdir(exist_ok=True)
    return make_tree(root, base=FINAL_BASE, fragments=True, temp_files=False, **kwargs)


def test_temporary_pins_fail_every_marker(tmp_path):
    (tmp_path / 'tools').mkdir()
    problems = '\n'.join(release_pins.local_problems(make_tree(tmp_path)))
    for marker in ('refs/heads/', 'temp-wheels', 'TEMP_REMOVE_BEFORE_RELEASE', 'tools/temp-wheels still exists'):
        assert marker in problems, marker


def test_a_dockerfile_temp_comment_alone_fails(tmp_path):
    final_tree(tmp_path)
    with (tmp_path / 'Dockerfile').open('a') as stream:
        stream.write('# TEMP-0.5.0-RELEASE-WHEELS: leftover\n')
    assert any('TEMP-' in problem for problem in release_pins.temp_problems(tmp_path))


def test_final_tree_passes(tmp_path):
    assert release_pins.local_problems(final_tree(tmp_path)) == []


@pytest.mark.parametrize('checksum', ['', 'abc', '0' * 63, 'G' * 64])
def test_empty_or_malformed_dockerfile_checksum_fails(tmp_path, checksum):
    problems = release_pins.local_problems(final_tree(tmp_path, sdist_hash=checksum))
    assert any('EMULATOR_SOURCE_SHA256' in problem for problem in problems)


def test_dockerfile_archive_must_match_the_locked_version(tmp_path):
    final_tree(tmp_path)
    path = tmp_path / 'Dockerfile'
    path.write_text(path.read_text().replace('0.1.1', '0.1.0'))
    assert any('does not match the locked pyboy-rs' in problem for problem in release_pins.local_problems(tmp_path))


def test_pyproject_url_without_a_matching_hash_fragment_fails(tmp_path):
    final_tree(tmp_path)
    path = tmp_path / 'pyproject.toml'
    path.write_text(path.read_text().replace('#sha256=' + HASHES[WHEEL], '#sha256=' + '0' * 64))
    assert any('fragment' in problem for problem in release_pins.local_problems(tmp_path))
    path.write_text(path.read_text().replace('#sha256=' + '0' * 64, ''))
    assert any('fragment' in problem for problem in release_pins.local_problems(tmp_path))


def test_remote_check_compares_published_bytes(tmp_path):
    final_tree(tmp_path)
    served = {FINAL_BASE + name: blob for name, blob in BLOBS.items()}
    assert release_pins.remote_problems(tmp_path, opener=lambda url: served[url.partition('#')[0]]) == []
    served[FINAL_BASE + WHEEL] = b'replaced after the lock was written'
    served[FINAL_BASE + SDIST] = b'another archive'
    problems = release_pins.remote_problems(tmp_path, opener=lambda url: served[url.partition('#')[0]])
    assert len(problems) == 2 and all('differs' in problem for problem in problems)


def test_remote_check_reports_unreachable_assets(tmp_path):
    final_tree(tmp_path)

    def offline(url):
        raise OSError('offline')

    assert len(release_pins.remote_problems(tmp_path, opener=offline)) == 3


def manifest(tmp_path, **changes):
    assets = {name: {'url': FINAL_BASE + name, 'sha256': digest} for name, digest in HASHES.items()}
    assets.update(changes)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps({'assets': assets, 'pyboy_rs_sdist': SDIST}))
    return path


def test_finalize_rewrites_everything_consistently(tmp_path):
    tree = tmp_path / 'tree'
    (tree / 'tools').mkdir(parents=True)
    make_tree(tree)
    assets, sdist = finalize_release_pins.load_manifest(manifest(tmp_path))
    finalize_release_pins.finalize(tree, assets, sdist)
    assert release_pins.local_problems(tree) == []
    assert not (tree / 'tools/temp-wheels').exists() and not (tree / 'TEMP_REMOVE_BEFORE_RELEASE.md').exists()
    assert '#sha256=' + HASHES[WHEEL] in (tree / 'pyproject.toml').read_text()
    assert 'temp' not in (tree / 'uv.lock').read_text().lower()


def test_finalize_takes_new_hashes_from_the_manifest(tmp_path):
    tree = tmp_path / 'tree'
    (tree / 'tools').mkdir(parents=True)
    make_tree(tree)
    new = '1' * 64
    assets, sdist = finalize_release_pins.load_manifest(manifest(tmp_path, **{WHEEL: {'url': FINAL_BASE + WHEEL, 'sha256': new}}))
    finalize_release_pins.finalize(tree, assets, sdist)
    assert f'hash = "sha256:{new}"' in (tree / 'uv.lock').read_text()
    assert f'#sha256={new}' in (tree / 'pyproject.toml').read_text()
    assert release_pins.local_problems(tree) == []


def test_finalize_refuses_an_incomplete_or_malformed_manifest(tmp_path):
    tree = tmp_path / 'tree'
    (tree / 'tools').mkdir(parents=True)
    make_tree(tree)
    path = tmp_path / 'incomplete.json'
    path.write_text(json.dumps({'assets': {SDIST: {'url': FINAL_BASE + SDIST, 'sha256': HASHES[SDIST]}}, 'pyboy_rs_sdist': SDIST}))
    assets, sdist = finalize_release_pins.load_manifest(path)
    with pytest.raises(SystemExit, match='lacks'):
        finalize_release_pins.finalize(tree, assets, sdist)
    with pytest.raises(SystemExit, match='branch ref'):
        finalize_release_pins.load_manifest(manifest(tmp_path, **{WHEEL: {'url': TEMP_BASE + WHEEL, 'sha256': HASHES[WHEEL]}}))
    with pytest.raises(SystemExit, match='64'):
        finalize_release_pins.load_manifest(manifest(tmp_path, **{WHEEL: {'url': FINAL_BASE + WHEEL, 'sha256': 'abc'}}))


def make_sdist(path, name, version):
    import io
    import tarfile
    info = f'Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n'.encode()
    with tarfile.open(path, 'w:gz') as archive:
        member = tarfile.TarInfo(f'{name}-{version}/PKG-INFO')
        member.size = len(info)
        archive.addfile(member, io.BytesIO(info))


def run_bundle(tmp_path, name, version):
    import subprocess
    archive = tmp_path / 'source.tar.gz'
    make_sdist(archive, name, version)
    return subprocess.run([sys.executable, str(Path(release_pins.ROOT) / 'tools/bundle_dependency_sources.py'),
                           str(tmp_path / 'out'), '--emulator-source', str(archive)], capture_output=True, text=True)


def test_bundled_emulator_source_must_match_the_locked_version(tmp_path):
    locked = release_pins.locked_version(release_pins.read_lock(release_pins.ROOT), 'pyboy-rs')
    good = run_bundle(tmp_path, 'pyboy_rs', locked)
    assert good.returncode == 0, good.stderr
    assert (tmp_path / 'out/sources' / f'pyboy-rs-{locked}.tar.gz').is_file()
    bad = run_bundle(tmp_path, 'pyboy_rs', '9.9.9')
    assert bad.returncode != 0 and 'uv.lock pins pyboy-rs' in bad.stderr
    other = run_bundle(tmp_path, 'something_else', locked)
    assert other.returncode != 0
