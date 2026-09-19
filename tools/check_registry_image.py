"""Require an anonymous pull of the exact image tested before publication."""
import argparse
import subprocess
import tempfile


def check(image):
    expected = subprocess.check_output(
        ['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
    with tempfile.TemporaryDirectory(prefix='pokesim-anonymous-') as config:
        try:
            subprocess.run(['docker', '--config', config, 'pull', image],
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
    print('Anonymous pull matches the tested image')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    check(parser.parse_args().image)
