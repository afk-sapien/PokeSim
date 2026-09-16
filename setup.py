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


def stamp(directory):
    path = Path(directory) / 'pokesim' / '_build.json'
    path.write_text(json.dumps(source_info(ROOT), indent=2) + '\n', encoding='utf-8')


class BuildPy(build_py):
    def run(self):
        super().run()
        stamp(self.build_lib)


class Sdist(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        stamp(base_dir)


setup(cmdclass={'build_py': BuildPy, 'sdist': Sdist})
