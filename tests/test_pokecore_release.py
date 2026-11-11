"""A pokecore release must match its tag and source, and the pin must move only to a verified release wheel."""
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from tools import release

ROOT = Path(__file__).resolve().parents[1]

OLD_URL = 'https://github.com/example/old/releases/download/v0.11.0/pokecore-0.11.0-py3-none-any.whl'
MARKER = "sys_platform == 'linux'"
CHANGELOG = '# Changelog\n\n## 0.11.1\n\n### Fixed\n\n- A fix.\n\n## 0.11.0\n\n- Older.\n'


def make_tree(root, version='0.11.1', init_version=None, changelog=CHANGELOG):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text(
        '[project]\nname = "pokesim"\nversion = "1.0.0"\ndependencies = [\n'
        '  "flask>=3",\n'
        f'  "pokecore[emulator] @ {OLD_URL}#sha256={"0" * 64} ; {MARKER}",\n]\n\n'
        '[tool.uv.workspace]\nmembers = ["packages/pokecore"]\n\n'
        '[tool.uv.sources]\npokecore = { workspace = true }\n', encoding='utf-8')
    member = root / 'packages' / 'pokecore'
    (member / 'src' / 'pokecore').mkdir(parents=True)
    (member / 'pyproject.toml').write_text(f'[project]\nname = "pokecore"\nversion = "{version}"\n', encoding='utf-8')
    (member / 'src' / 'pokecore' / '__init__.py').write_text(
        f'"""Core."""\n__version__ = "{init_version or version}"\n', encoding='utf-8')
    (member / 'src' / 'pokecore' / 'gen1.py').write_text('W_X = 1\n', encoding='utf-8')
    (member / 'CHANGELOG.md').write_text(changelog, encoding='utf-8')
    return root


def build_wheel(root, version='0.11.1', change=None):
    """A wheel of the member source, with one file's bytes replaced when change is (path, bytes)."""
    source = root / 'packages' / 'pokecore' / 'src' / 'pokecore'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for path in sorted(source.rglob('*')):
            name = 'pokecore/' + path.relative_to(source).as_posix()
            data = change[1] if change and change[0] == name else path.read_bytes()
            archive.writestr(name, data)
        archive.writestr(f'pokecore-{version}.dist-info/METADATA', f'Name: pokecore\nVersion: {version}\n')
    return buffer.getvalue()


def opener_for(wheel, version='0.11.1', listed=None):
    url = release.wheel_url(version)
    sums = f'{listed or hashlib.sha256(wheel).hexdigest()}  {url.rsplit("/", 1)[-1]}\n'
    sums += f'{"1" * 64}  pokecore-{version}.tar.gz\n'
    files = {url: wheel, url.rsplit('/', 1)[0] + '/SHA256SUMS.txt': sums.encode()}

    def opener(target):
        if target not in files:
            raise OSError(f'404 {target}')
        return files[target]
    return opener


def test_a_matching_tag_gives_its_version_and_only_its_changelog_section(tmp_path):
    version, notes, problems = release.check_pokecore(make_tree(tmp_path), 'pokecore-v0.11.1')
    assert (version, problems) == ('0.11.1', [])
    assert notes == '### Fixed\n\n- A fix.'


@pytest.mark.parametrize('tag', ['v0.11.1', 'pokecore-0.11.1', 'pokecore-v0.11', 'pokecore-v0.11.1-dirty'])
def test_a_tag_that_is_not_pokecore_v_semver_is_refused(tmp_path, tag):
    assert release.check_pokecore(make_tree(tmp_path), tag)[2] == [f'{tag!r} is not a pokecore-vX.Y.Z tag']


def test_a_release_candidate_tag_is_allowed(tmp_path):
    tree = make_tree(tmp_path, version='0.12.0rc1', changelog='## 0.12.0rc1\n\n- Trial.\n')
    assert release.check_pokecore(tree, 'pokecore-v0.12.0rc1')[::2] == ('0.12.0rc1', [])


def test_versions_that_disagree_with_the_tag_are_each_reported(tmp_path):
    problems = release.check_pokecore(make_tree(tmp_path, version='0.11.0', init_version='0.10.2'), 'pokecore-v0.11.1')[2]
    assert problems == ['packages/pokecore/pyproject.toml is 0.11.0, not 0.11.1',
                        'pokecore.__version__ is 0.10.2, not 0.11.1']


@pytest.mark.parametrize('changelog', ['## 0.11.0\n\n- Older.\n', '## 0.11.1\n\n## 0.11.0\n\n- Older.\n'])
def test_a_missing_or_empty_changelog_section_is_refused(tmp_path, changelog):
    problems = release.check_pokecore(make_tree(tmp_path, changelog=changelog), 'pokecore-v0.11.1')[2]
    assert problems == ['packages/pokecore/CHANGELOG.md has no "## 0.11.1" section with text']


def test_the_command_prints_the_version_output_and_writes_the_notes(tmp_path, capsys):
    tree = make_tree(tmp_path / 'tree')
    wheel = tmp_path / 'pokecore-0.11.1-py3-none-any.whl'
    wheel.write_bytes(build_wheel(tree))
    release.main(['check-pokecore', 'pokecore-v0.11.1','--root', str(tree), '--notes', str(tmp_path / 'notes.md'),
                           '--wheel', str(wheel)])
    assert capsys.readouterr().out == 'version=0.11.1\n'
    assert (tmp_path / 'notes.md').read_text() == '### Fixed\n\n- A fix.\n'


def test_the_command_fails_on_a_wheel_that_differs_from_the_source(tmp_path):
    tree = make_tree(tmp_path / 'tree')
    wheel = tmp_path / 'pokecore-0.11.1-py3-none-any.whl'
    wheel.write_bytes(build_wheel(tree, change=('pokecore/gen1.py', b'W_X = 2\n')))
    with pytest.raises(SystemExit, match='differs from the workspace source: pokecore/gen1.py'):
        release.main(['check-pokecore', 'pokecore-v0.11.1','--root', str(tree), '--wheel', str(wheel)])


def test_a_wheel_named_for_another_version_is_refused(tmp_path):
    tree = make_tree(tmp_path / 'tree')
    wheel = tmp_path / 'pokecore-0.11.0-py3-none-any.whl'
    wheel.write_bytes(build_wheel(tree))
    assert release.wheel_problems(tree, '0.11.1', wheel) == [
        'built wheel is pokecore-0.11.0-py3-none-any.whl, expected pokecore-0.11.1-py3-none-any.whl']


def test_pin_rewrites_only_the_url_and_fragment(tmp_path):
    tree = make_tree(tmp_path)
    before = (tree / 'pyproject.toml').read_text()
    wheel = build_wheel(tree)
    assert release.pin(tree, '0.11.1', opener_for(wheel)) == []
    after = (tree / 'pyproject.toml').read_text()
    url = release.wheel_url('0.11.1')
    assert url == 'https://github.com/afk-sapien/PokeSim/releases/download/pokecore-v0.11.1/pokecore-0.11.1-py3-none-any.whl'
    assert after == before.replace(f'{OLD_URL}#sha256={"0" * 64}', f'{url}#sha256={hashlib.sha256(wheel).hexdigest()}')
    assert f'"pokecore[emulator] @ {url}#sha256=' in after and f' ; {MARKER}",' in after


@pytest.mark.parametrize('case, expected', [
    ('unlisted', 'but SHA256SUMS.txt lists ' + 'f' * 64),
    ('differs', 'published pokecore wheel differs from the workspace source: pokecore/gen1.py'),
    ('version', 'packages/pokecore is 0.11.1, not 0.11.2, so its source is not that release'),
    ('missing', 'could not download the pokecore-v0.11.1 release files: 404'),
])
def test_pin_refuses_an_unverified_wheel_and_leaves_pyproject_alone(tmp_path, case, expected):
    tree = make_tree(tmp_path)
    before = (tree / 'pyproject.toml').read_text()
    wheel = build_wheel(tree, change=('pokecore/gen1.py', b'W_X = 2\n') if case == 'differs' else None)
    opener = opener_for(wheel, listed='f' * 64 if case == 'unlisted' else None)
    if case == 'missing':
        opener = opener_for(wheel, version='9.9.9')
    problems = release.pin(tree, '0.11.2' if case == 'version' else '0.11.1', opener)
    assert len(problems) == 1 and expected in problems[0], problems
    assert (tree / 'pyproject.toml').read_text() == before


def test_pin_refuses_a_pyproject_without_exactly_one_pokecore_url(tmp_path):
    tree = make_tree(tmp_path)
    path = tree / 'pyproject.toml'
    path.write_text(path.read_text().replace('"flask>=3"', f'"pokecore @ {OLD_URL}#sha256={"0" * 64}"'))
    before = path.read_text()
    assert release.pin(tree, '0.11.1', opener_for(build_wheel(tree))) == [
        'pyproject.toml has 2 pokecore URL requirements, expected exactly one']
    assert path.read_text() == before


def test_the_repository_pin_is_the_one_requirement_the_rewrite_finds():
    assert len(release.REQUIREMENT.findall((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))) == 1


def workflow():
    return yaml.safe_load((ROOT / '.github/workflows/pokecore-release.yml').read_text(encoding='utf-8'))


def test_the_release_runs_only_by_hand_with_read_only_defaults():
    flow = workflow()
    on = flow.get('on', flow.get(True))
    assert list(on) == ['workflow_dispatch'] and set(on['workflow_dispatch']['inputs']) == {'tag', 'dry_run'}
    assert flow['permissions'] == {'contents': 'read'}


def test_publish_is_the_only_writer_and_waits_for_the_tests_and_the_build():
    jobs = workflow()['jobs']
    writes = ('gh release create', 'gh release upload', 'gh release edit', 'gh release delete')
    writers = [name for name, job in jobs.items()
               if job.get('permissions', {}).get('contents') == 'write'
               or any(write in step.get('run', '') for step in job['steps'] for write in writes)]
    assert writers == ['publish']
    assert jobs['publish']['if'] == '${{ inputs.dry_run != true }}'
    assert set(jobs['publish']['needs']) == {'validate', 'package'} and 'test' in jobs['package']['needs']


def test_every_release_create_and_edit_keeps_the_latest_release_on_pokesim():
    text = (ROOT / '.github/workflows/pokecore-release.yml').read_text(encoding='utf-8')
    commands = re.findall(r'gh release (?:create|edit) .*', text)
    assert len(commands) == 3
    assert all('--latest=false' in command for command in commands)
    assert not re.search(r'--latest(?!=false)', text)


def test_validation_checks_the_tag_and_that_main_holds_the_commit():
    check = next(step['run'] for step in workflow()['jobs']['validate']['steps'] if step.get('id') == 'check')
    assert 'python tools/release.py check-pokecore "$TAG"' in check
    assert 'git merge-base --is-ancestor "$revision" origin/main' in check
    package = '\n'.join(step.get('run', '') for step in workflow()['jobs']['package']['steps'])
    assert '--wheel "dist/pokecore-$VERSION-py3-none-any.whl"' in package and 'sha256sum -c' in package
