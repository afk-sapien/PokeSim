"""Checkouts and environments for older commits, kept in a cache folder.

A commit's checkout is ``git archive`` of it under ``trees/<sha>``. Its environment is synced
from that checkout's own lock under ``envs/<key>``, where the key covers the lock, the pokecore
member's tree when the commit has one, and the pyboy-rs choice. Commits that share all three
share one environment. The pyboy-rs choice is ``current``, the wheel the running checkout's
lock names for this machine, or ``own``, the one the commit's lock names. Holding one pyboy-rs
across a bisect keeps an emulator change out of the search.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / 'data' / 'replay-cache'
READY = '.replay-ready'
CURRENT, OWN = 'current', 'own'
SYNC_TIMEOUT = 1800


def git(*args, root=ROOT):
    done = subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def resolve(ref, root=ROOT):
    """The full commit id of ``ref``."""
    return git('rev-parse', '--verify', f'{ref}^{{commit}}', root=root)


@contextlib.contextmanager
def _locked(cache, name):
    """Hold a lock on ``name`` across threads and processes that share the cache."""
    folder = Path(cache) / 'locks'
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f'{name}.lock', 'a+b') as handle:
        try:
            import fcntl
        except ImportError:  # No file locks here. One tool at a time then.
            yield
            return
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def tree(sha, cache=DEFAULT_CACHE, root=ROOT):
    """The checkout of commit ``sha``, extracted once."""
    target = Path(cache) / 'trees' / sha
    if (target / READY).exists():
        return target
    with _locked(cache, f'tree-{sha}'):
        if (target / READY).exists():
            return target
        partial = target.with_name(f'.{sha}.{os.getpid()}.partial')
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        archive = subprocess.Popen(['git', '-C', str(root), 'archive', sha], stdout=subprocess.PIPE)
        try:
            subprocess.run(['tar', 'x', '-C', str(partial)], stdin=archive.stdout, check=True)
        finally:
            archive.stdout.close()
            failed = archive.wait()
        if failed:
            raise RuntimeError(f'git archive {sha} failed with {failed}')
        (partial / READY).write_text(sha + '\n', encoding='utf-8')
        shutil.rmtree(target, ignore_errors=True)
        os.replace(partial, target)
    return target


def _machine_names():
    machine = platform.machine().lower()
    for names in (('x86_64', 'amd64'), ('aarch64', 'arm64')):
        if machine in names:
            return names
    return (machine,)


def wheel_for_machine(lock, package='pyboy-rs'):
    """(version, URL with its hash) of the ``package`` wheel that ``lock`` names for this machine."""
    system = {'linux': 'manylinux', 'darwin': 'macosx', 'win32': 'win_'}.get(sys.platform, sys.platform)
    names = _machine_names()
    for entry in lock.get('package', []):
        if entry.get('name') != package:
            continue
        for wheel in entry.get('wheels', []):
            file = wheel['url'].rsplit('/', 1)[-1].lower()
            if system in file and any(name in file for name in names):
                digest = wheel.get('hash', '').replace(':', '=', 1)
                return entry['version'], wheel['url'] + (f'#{digest}' if digest else '')
    raise LookupError(f'the lock names no {package} wheel for {sys.platform} {platform.machine()}')


def current_pyboy(root=ROOT):
    """The pyboy-rs wheel the running checkout's lock names for this machine."""
    return wheel_for_machine(tomllib.loads((Path(root) / 'uv.lock').read_text(encoding='utf-8')))


def env_key(lock, core_tree, pyboy):
    """The cache key of an environment: the lock's bytes, the pokecore tree id or None, the pyboy choice."""
    parts = [hashlib.sha256(lock).hexdigest(), core_tree or '-', pyboy]
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:20]


def _core_tree(sha, root):
    try:
        return git('rev-parse', '--verify', f'{sha}:packages/pokecore', root=root)
    except subprocess.CalledProcessError:
        return None


def environment(sha, checkout, pyboy=CURRENT, cache=DEFAULT_CACHE, root=ROOT, log=print):
    """The environment for commit ``sha`` whose checkout is ``checkout``, synced once.

    Returns (folder, pyboy-rs version installed in it).
    """
    lock = (Path(checkout) / 'uv.lock').read_bytes()
    wheel = None
    if pyboy == CURRENT:
        version, wheel = current_pyboy(root)
        choice = wheel
    elif pyboy == OWN:
        version, _ = wheel_for_machine(tomllib.loads(lock.decode('utf-8')))
        choice = OWN
    else:
        raise ValueError(f'pyboy is {CURRENT} or {OWN}, not {pyboy}')
    folder = Path(cache) / 'envs' / env_key(lock, _core_tree(sha, root), choice)
    ready = folder / READY
    if ready.exists():
        return folder, json.loads(ready.read_text(encoding='utf-8'))['pyboy']
    with _locked(cache, f'env-{folder.name}'):
        if ready.exists():
            return folder, json.loads(ready.read_text(encoding='utf-8'))['pyboy']
        shutil.rmtree(folder, ignore_errors=True)
        log(f'syncing an environment for {sha[:12]} with pyboy-rs {version}')
        env = {name: value for name, value in os.environ.items() if name not in ('VIRTUAL_ENV', 'PYTHONPATH')}
        env['UV_PROJECT_ENVIRONMENT'] = str(folder)
        subprocess.run(['uv', 'sync', '-q', '--locked', '--no-dev', '--no-install-project', '--no-editable',
                        '--project', str(checkout)], check=True, env=env, timeout=SYNC_TIMEOUT)
        if wheel is not None:
            subprocess.run(['uv', 'pip', 'install', '-q', '--python', str(python(folder)), '--no-deps',
                            '--reinstall-package', 'pyboy-rs', f'pyboy-rs @ {wheel}'],
                           check=True, env=env, timeout=SYNC_TIMEOUT)
        ready.write_text(json.dumps({'commit': sha, 'pyboy': version, 'choice': choice}) + '\n', encoding='utf-8')
    return folder, version


def python(env):
    env = Path(env)
    return env / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
