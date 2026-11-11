"""A public release must not carry the temporary wheel pins, and its pins must agree with each other."""
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

from tools import release

TEMP_BASE = 'https://raw.githubusercontent.com/example/PokeSim/refs/heads/release/9.9.9/tools/temp-wheels/'
FINAL_BASE = 'https://github.com/example/pyboy-rs/releases/download/v0.1.1/'
WHEEL = 'pyboy_rs-0.1.1-cp311-abi3-win_amd64.whl'
CORE = 'pokecore-0.2.0-py3-none-any.whl'
SDIST = 'pyboy_rs-0.1.1.tar.gz'
BLOBS = {WHEEL: b'wheel bytes', CORE: b'core bytes', SDIST: b'sdist bytes'}
HASHES = {name: hashlib.sha256(blob).hexdigest() for name, blob in BLOBS.items()}


def make_tree(root, base=TEMP_BASE, fragments=False, sdist_hash=None, temp_files=True):
    def url(name):
        return base + name + (('#sha256=' + HASHES[name]) if fragments else '')

    (root / 'pyproject.toml').write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\ndependencies = [\n'
        f'  "pokecore[emulator] @ {url(CORE)}",\n'
        f'  "pyboy-rs @ {url(WHEEL)} ; sys_platform == \'win32\'",\n]\n')
    lock = ''
    for name, package in ((CORE, 'pokecore'), (WHEEL, 'pyboy-rs')):
        version = '0.2.0' if package == 'pokecore' else '0.1.1'
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
    problems = '\n'.join(release.local_problems(make_tree(tmp_path)))
    for marker in ('refs/heads/', 'temp-wheels', 'TEMP_REMOVE_BEFORE_RELEASE', 'tools/temp-wheels still exists'):
        assert marker in problems, marker


def test_a_dockerfile_temp_comment_alone_fails(tmp_path):
    final_tree(tmp_path)
    with (tmp_path / 'Dockerfile').open('a') as stream:
        stream.write('# TEMP-0.5.0-RELEASE-WHEELS: leftover\n')
    assert any('TEMP-' in problem for problem in release.temp_problems(tmp_path))


def test_final_tree_passes(tmp_path):
    assert release.local_problems(final_tree(tmp_path)) == []


@pytest.mark.parametrize('checksum', ['', 'abc', '0' * 63, 'G' * 64])
def test_empty_or_malformed_dockerfile_checksum_fails(tmp_path, checksum):
    problems = release.local_problems(final_tree(tmp_path, sdist_hash=checksum))
    assert any('EMULATOR_SOURCE_SHA256' in problem for problem in problems)


def test_dockerfile_archive_must_match_the_locked_version(tmp_path):
    final_tree(tmp_path)
    path = tmp_path / 'Dockerfile'
    path.write_text(path.read_text().replace('0.1.1', '0.1.0'))
    assert any('does not match the locked pyboy-rs' in problem for problem in release.local_problems(tmp_path))


def test_pyproject_url_without_a_matching_hash_fragment_fails(tmp_path):
    final_tree(tmp_path)
    path = tmp_path / 'pyproject.toml'
    path.write_text(path.read_text().replace('#sha256=' + HASHES[WHEEL], '#sha256=' + '0' * 64))
    assert any('fragment' in problem for problem in release.local_problems(tmp_path))
    path.write_text(path.read_text().replace('#sha256=' + '0' * 64, ''))
    assert any('fragment' in problem for problem in release.local_problems(tmp_path))


def test_remote_check_compares_published_bytes(tmp_path):
    final_tree(tmp_path)
    served = {FINAL_BASE + name: blob for name, blob in BLOBS.items()}
    assert release.remote_problems(tmp_path, opener=lambda url: served[url.partition('#')[0]]) == []
    served[FINAL_BASE + WHEEL] = b'replaced after the lock was written'
    served[FINAL_BASE + SDIST] = b'another archive'
    problems = release.remote_problems(tmp_path, opener=lambda url: served[url.partition('#')[0]])
    assert len(problems) == 2 and all('differs' in problem for problem in problems)


def test_remote_check_reports_unreachable_assets(tmp_path):
    final_tree(tmp_path)

    def offline(url):
        raise OSError('offline')

    assert len(release.remote_problems(tmp_path, opener=offline)) == 3


def workspace_tree(root, member_version='0.2.0', fragment=True):
    """Today's shape: uv locks pokecore from packages/pokecore, and the URL pin is the released wheel for pip."""
    final_tree(root)
    core = FINAL_BASE + CORE + (('#sha256=' + HASHES[CORE]) if fragment else '')
    (root / 'pyproject.toml').write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\ndependencies = [\n'
        f'  "pokecore[emulator] @ {core} ; sys_platform == \'win32\'",\n'
        f'  "pyboy-rs @ {FINAL_BASE + WHEEL}#sha256={HASHES[WHEEL]} ; sys_platform == \'win32\'",\n]\n\n'
        '[tool.uv.workspace]\nmembers = ["packages/pokecore"]\n\n[tool.uv.sources]\npokecore = { workspace = true }\n')
    (root / 'packages/pokecore/src/pokecore').mkdir(parents=True)
    (root / 'packages/pokecore/pyproject.toml').write_text(f'[project]\nname = "pokecore"\nversion = "{member_version}"\n')
    (root / 'packages/pokecore/src/pokecore/__init__.py').write_bytes(b'VERSION = 1\n')
    (root / 'uv.lock').write_text(
        f'[[package]]\nname = "pokecore"\nversion = "{member_version}"\nsource = {{ editable = "packages/pokecore" }}\n\n'
        f'[[package]]\nname = "pyboy-rs"\nversion = "0.1.1"\nsource = {{ url = "{FINAL_BASE + WHEEL}" }}\n'
        f'wheels = [\n    {{ url = "{FINAL_BASE + WHEEL}", hash = "sha256:{HASHES[WHEEL]}" }},\n]\n')
    return root


def core_wheel(files):
    import zipfile
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, blob in files.items():
            archive.writestr(name, blob)
        archive.writestr('pokecore-0.2.0.dist-info/METADATA', 'Name: pokecore\n')
    return stream.getvalue()


def test_a_workspace_member_pin_at_the_member_version_passes(tmp_path):
    assert release.local_problems(workspace_tree(tmp_path)) == []


def test_a_workspace_member_pin_at_another_version_fails(tmp_path):
    problems = release.local_problems(workspace_tree(tmp_path, member_version='0.3.0'))
    assert problems == [f'pyproject pins pokecore 0.2.0 but packages/pokecore is 0.3.0: {FINAL_BASE + CORE}']


def test_a_workspace_member_pin_needs_a_hash_fragment(tmp_path):
    problems = release.local_problems(workspace_tree(tmp_path, fragment=False))
    assert problems == [f'pyproject URL lacks a #sha256 fragment: {FINAL_BASE + CORE}']


def test_remote_check_compares_a_workspace_member_wheel_with_its_fragment_and_source(tmp_path):
    workspace_tree(tmp_path)
    wheel = core_wheel({'pokecore/__init__.py': b'VERSION = 1\n'})
    served = {FINAL_BASE + WHEEL: BLOBS[WHEEL], FINAL_BASE + SDIST: BLOBS[SDIST], FINAL_BASE + CORE: wheel}
    path = tmp_path / 'pyproject.toml'
    path.write_text(path.read_text().replace(HASHES[CORE], hashlib.sha256(wheel).hexdigest()))
    assert release.remote_problems(tmp_path, opener=lambda url: served[url.partition('#')[0]]) == []
    (tmp_path / 'packages/pokecore/src/pokecore/__init__.py').write_bytes(b'VERSION = 2\n')
    (tmp_path / 'packages/pokecore/src/pokecore/new.py').write_bytes(b'')
    problems = release.remote_problems(tmp_path, opener=lambda url: served[url.partition('#')[0]])
    assert problems == ['published pokecore wheel differs from the workspace source: '
                        'pokecore/__init__.py, pokecore/new.py']
    served[FINAL_BASE + CORE] = b'not a wheel'
    problems = release.remote_problems(tmp_path, opener=lambda url: served[url.partition('#')[0]])
    assert [problem.split(':')[0] for problem in problems] == ['published asset differs from the pyproject fragment',
                                                               'published asset is not a wheel']


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
    assets, sdist = release.load_manifest(manifest(tmp_path))
    release.finalize(tree, assets, sdist)
    assert release.local_problems(tree) == []
    assert not (tree / 'tools/temp-wheels').exists() and not (tree / 'TEMP_REMOVE_BEFORE_RELEASE.md').exists()
    assert '#sha256=' + HASHES[WHEEL] in (tree / 'pyproject.toml').read_text()
    assert 'temp' not in (tree / 'uv.lock').read_text().lower()


def test_finalize_takes_new_hashes_from_the_manifest(tmp_path):
    tree = tmp_path / 'tree'
    (tree / 'tools').mkdir(parents=True)
    make_tree(tree)
    new = '1' * 64
    assets, sdist = release.load_manifest(manifest(tmp_path, **{WHEEL: {'url': FINAL_BASE + WHEEL, 'sha256': new}}))
    release.finalize(tree, assets, sdist)
    assert f'hash = "sha256:{new}"' in (tree / 'uv.lock').read_text()
    assert f'#sha256={new}' in (tree / 'pyproject.toml').read_text()
    assert release.local_problems(tree) == []


def test_finalize_refuses_an_incomplete_or_malformed_manifest(tmp_path):
    tree = tmp_path / 'tree'
    (tree / 'tools').mkdir(parents=True)
    make_tree(tree)
    path = tmp_path / 'incomplete.json'
    path.write_text(json.dumps({'assets': {SDIST: {'url': FINAL_BASE + SDIST, 'sha256': HASHES[SDIST]}}, 'pyboy_rs_sdist': SDIST}))
    assets, sdist = release.load_manifest(path)
    with pytest.raises(SystemExit, match='lacks'):
        release.finalize(tree, assets, sdist)
    with pytest.raises(SystemExit, match='branch ref'):
        release.load_manifest(manifest(tmp_path, **{WHEEL: {'url': TEMP_BASE + WHEEL, 'sha256': HASHES[WHEEL]}}))
    with pytest.raises(SystemExit, match='64'):
        release.load_manifest(manifest(tmp_path, **{WHEEL: {'url': FINAL_BASE + WHEEL, 'sha256': 'abc'}}))


def path_sourced_tree(root):
    """The 0.5.0 candidate's shape: Core locked from tools/temp-wheels through [tool.uv.sources]."""
    (root / 'tools/temp-wheels').mkdir(parents=True)
    (root / 'tools/temp-wheels' / CORE).write_bytes(BLOBS[CORE])
    (root / 'TEMP_REMOVE_BEFORE_RELEASE.md').write_text('# TEMP\n')
    (root / 'pyproject.toml').write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\ndependencies = [\n'
        f'  "pokecore[emulator] @ {TEMP_BASE + CORE}#sha256={HASHES[CORE]} ; sys_platform == \'linux\'",\n'
        f'  "pyboy-rs @ {FINAL_BASE + WHEEL}#sha256={HASHES[WHEEL]} ; sys_platform == \'win32\'",\n]\n\n'
        '# TEMP: lock Core from the copy in tools/temp-wheels.\n[tool.uv.sources]\n'
        f'pokecore = {{ path = "tools/temp-wheels/{CORE}" }}\n\n[tool.uv]\nrequired-version = ">=0.9"\n')
    (root / 'uv.lock').write_text(
        '[[package]]\nname = "pokecore"\nversion = "0.2.0"\n'
        f'source = {{ path = "tools/temp-wheels/{CORE}" }}\n'
        f'wheels = [\n    {{ filename = "{CORE}", hash = "sha256:{HASHES[CORE]}" }},\n]\n\n'
        '[[package]]\nname = "pyboy-rs"\nversion = "0.1.1"\n'
        f'source = {{ url = "{FINAL_BASE + WHEEL}" }}\n'
        f'wheels = [\n    {{ url = "{FINAL_BASE + WHEEL}", hash = "sha256:{HASHES[WHEEL]}" }},\n]\n\n'
        '[package.metadata]\nrequires-dist = [\n'
        f'    {{ name = "pokecore", extras = ["emulator"], path = "tools/temp-wheels/{CORE}" }},\n]\n')
    (root / 'Dockerfile').write_text(
        'COPY pokesim ./pokesim\n# TEMP: uv.lock reads Core from this copy.\nCOPY tools/temp-wheels ./tools/temp-wheels\n'
        f'ARG EMULATOR_SOURCE_URL={FINAL_BASE + SDIST}\nARG EMULATOR_SOURCE_SHA256={HASHES[SDIST]}\n')
    return root


def test_pin_check_reports_a_path_sourced_wheel_instead_of_crashing(tmp_path):
    problems = release.local_problems(path_sourced_tree(tmp_path))
    assert any('pyproject URL is not in uv.lock' in problem for problem in problems)


def test_finalize_rewrites_a_path_sourced_tree(tmp_path):
    tree = path_sourced_tree(tmp_path / 'tree')
    assets, sdist = release.load_manifest(manifest(tmp_path))
    release.finalize(tree, assets, sdist)
    assert release.local_problems(tree) == []
    pyproject = (tree / 'pyproject.toml').read_text()
    assert pyproject.count('#sha256=' + HASHES[CORE]) == 1 and 'tool.uv.sources' not in pyproject
    assert '[tool.uv]' in pyproject
    assert 'temp' not in (tree / 'Dockerfile').read_text().lower()
    assert f'source = {{ url = "{FINAL_BASE + CORE}" }}' in (tree / 'uv.lock').read_text()
    assert sorted(path.name for path in tree.iterdir()) == ['Dockerfile', 'pyproject.toml', 'tools', 'uv.lock']


def test_finalize_changes_nothing_when_its_result_fails_the_checks(tmp_path):
    tree = path_sourced_tree(tmp_path / 'tree')
    before = {path: path.read_bytes() for path in tree.rglob('*') if path.is_file()}
    other = 'pyboy_rs-0.1.0.tar.gz'
    # The archive does not match the locked pyboy-rs version, which only the final check notices.
    assets = {name: {'url': FINAL_BASE + name, 'sha256': HASHES[name]} for name in (CORE, WHEEL)}
    assets[other] = {'url': FINAL_BASE + other, 'sha256': HASHES[SDIST]}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps({'assets': assets, 'pyboy_rs_sdist': other}))
    assets, sdist = release.load_manifest(path)
    with pytest.raises(SystemExit, match='nothing was changed'):
        release.finalize(tree, assets, sdist)
    assert {path: path.read_bytes() for path in tree.rglob('*') if path.is_file()} == before


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
    return subprocess.run([sys.executable, str(Path(release.ROOT) / 'tools/bundle_dependency_sources.py'),
                           str(tmp_path / 'out'), '--emulator-source', str(archive)], capture_output=True, text=True)


def test_bundled_emulator_source_must_match_the_locked_version(tmp_path):
    locked = release.locked_version(release.read_lock(release.ROOT), 'pyboy-rs')
    good = run_bundle(tmp_path, 'pyboy_rs', locked)
    assert good.returncode == 0, good.stderr
    assert (tmp_path / 'out/sources' / f'pyboy-rs-{locked}.tar.gz').is_file()
    bad = run_bundle(tmp_path, 'pyboy_rs', '9.9.9')
    assert bad.returncode != 0 and 'uv.lock pins pyboy-rs' in bad.stderr
    other = run_bundle(tmp_path, 'something_else', locked)
    assert other.returncode != 0
