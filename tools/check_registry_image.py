"""Require an anonymous pull of the exact image tested before publication."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile


def local_identity(image):
    """The platform, creation time, layers and labels of a local image.

    The image ID cannot identify an image across machines. It is the config digest under the classic image
    store and the digest of the pulled tag under the containerd store. These fields are the same under both.
    """
    data = json.loads(subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{json .}}', image]))
    return {'platform': f"{data['Os']}/{data['Architecture']}", 'created': data['Created'],
            'layers': data['RootFS']['Layers'], 'labels': data['Config'].get('Labels') or {}}


def registry_identities(image, env=None):
    """The same identity for each runnable platform the registry serves under `image`."""
    try:
        raw = subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', '--format', '{{json .Image}}',
                                       image], env=env, stderr=subprocess.PIPE, timeout=300)
    except subprocess.CalledProcessError as error:
        raise LookupError((error.stderr or b'').decode(errors='replace').strip()) from error
    data = json.loads(raw)
    # A single image gives its config. A multi-platform index gives a config per platform.
    configs = [data] if 'rootfs' in data else [value for value in data.values()
                                               if isinstance(value, dict) and 'rootfs' in value]
    return {f"{config['os']}/{config['architecture']}": {
        'platform': f"{config['os']}/{config['architecture']}", 'created': config['created'],
        'layers': config['rootfs']['diff_ids'], 'labels': config.get('config', {}).get('Labels') or {}}
        for config in configs}


def check(image, tested=None, platform=None):
    """Pull `image` anonymously for `platform` and compare it with the local `tested` image."""
    expected = local_identity(tested or image)
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
        served = registry_identities(image, env={**os.environ, 'DOCKER_CONFIG': config})
    if served.get(platform or expected['platform']) != expected:
        raise ValueError('The registry image differs from the tested local image')
    print('Anonymous pull matches the tested image', platform or '')


def check_unchanged(image, tested=None, platform=None):
    """Refuse to push over a registry tag that already serves a different image. A missing tag passes."""
    expected = local_identity(tested or image)
    try:
        served = registry_identities(image)
    except LookupError as error:
        if 'not found' not in str(error).lower():
            raise
        print(image, 'is not in the registry yet')
        return
    if served.get(platform or expected['platform']) != expected:
        raise ValueError(f'{image} already serves a different image. Publish a new version instead.')
    print(image, 'already serves the tested image', platform or '')


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
    parser.add_argument('--unchanged', action='store_true',
                        help='before a push: fail if the registry tag exists and serves a different image')
    arguments = parser.parse_args()
    if arguments.index:
        print(check_index(arguments.image, arguments.index.split(',')))
    elif arguments.unchanged:
        check_unchanged(arguments.image, arguments.tested, arguments.platform)
    else:
        check(arguments.image, arguments.tested, arguments.platform)
