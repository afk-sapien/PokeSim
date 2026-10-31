"""Require an anonymous pull of the exact image tested before publication."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile


def check(image, tested=None, platform=None):
    """Pull `image` anonymously for `platform` and compare it with the local `tested` image."""
    expected = subprocess.check_output(
        ['docker', 'image', 'inspect', '--format', '{{.Id}}', tested or image], text=True).strip()
    with tempfile.TemporaryDirectory(prefix='pokesim-anonymous-') as config:
        try:
            subprocess.run(['docker', '--config', config, 'pull',
                            *(['--platform', platform] if platform else []), image],
                           check=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                'Anonymous image pull failed. For the first publication, open the '
                'pokesim package settings on GitHub, change its visibility to Public, '
                'then rerun the release workflow. Also check GHCR availability. '
                'The GitHub release has not been published.') from error
    actual = subprocess.check_output(
        ['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
    if actual != expected:
        raise ValueError('The registry image differs from the tested local image')
    print('Anonymous pull matches the tested image', platform or '')


def check_index(image, platforms):
    """Return the digest of the anonymous multi-platform index after checking its platforms."""
    with tempfile.TemporaryDirectory(prefix='pokesim-anonymous-') as config:
        raw = subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', '--raw', image],
                                      env={**os.environ, 'DOCKER_CONFIG': config}, timeout=300)
    index = json.loads(raw)
    # Build attestations appear as unknown/unknown entries and are not runnable platforms.
    found = sorted(f"{entry['platform']['os']}/{entry['platform']['architecture']}"
                   for entry in index.get('manifests', [])
                   if entry.get('platform', {}).get('os', 'unknown') != 'unknown')
    if found != sorted(platforms):
        raise ValueError(f'The registry image serves {found or "no platform list"}, not {sorted(platforms)}')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--tested', help='local image the pull must match (default: the image itself)')
    parser.add_argument('--platform', help='platform to pull from a multi-platform image')
    parser.add_argument('--index', metavar='PLATFORMS',
                        help='comma-separated platforms the index must serve. Prints the index digest.')
    arguments = parser.parse_args()
    if arguments.index:
        print(check_index(arguments.image, arguments.index.split(',')))
    else:
        check(arguments.image, arguments.tested, arguments.platform)
