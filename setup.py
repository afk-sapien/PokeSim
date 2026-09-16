"""Embed source identity without requiring Git on installed machines."""
import json
from pathlib import Path
import sys

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pokesim.build_info import source_info


def stamp(directory, identity):
    path = Path(directory) / 'pokesim' / '_build.json'
    path.write_text(json.dumps(identity, indent=2) + '\n', encoding='utf-8')


class BuildPy(build_py):
    def run(self):
        identity = source_info(ROOT)
        super().run()
        stamp(self.build_lib, identity)


class Sdist(sdist):
    def make_release_tree(self, base_dir, files):
        # Capture the checkout before setuptools creates its untracked staging tree.
        identity = source_info(ROOT)
        super().make_release_tree(base_dir, files)
        stamp(base_dir, identity)


setup(cmdclass={'build_py': BuildPy, 'sdist': Sdist})
