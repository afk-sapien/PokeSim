"""Name the floating image tags a published release should move.

`latest` follows the newest stable release, and `<major>.<minor>` follows the newest stable
release of that line, so a fix to an older line never moves `latest` back. Release
candidates move nothing.
"""
import argparse
import re

STABLE = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')


def stable(tag):
    match = STABLE.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def floating(version, published):
    current = stable(version)
    if current is None:
        return []
    releases = [release for release in map(stable, published) if release] + [current]
    tags = []
    if current >= max(releases):
        tags.append('latest')
    if current >= max(release for release in releases if release[:2] == current[:2]):
        tags.append(f'{current[0]}.{current[1]}')
    return tags


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    parser.add_argument('published', nargs='*', help='tags of the published releases')
    arguments = parser.parse_args()
    print('\n'.join(floating(arguments.version, arguments.published)))
