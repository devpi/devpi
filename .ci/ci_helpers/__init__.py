from .flake8 import Flake8
from .git import Git
from .ruff import Ruff
from functools import cached_property


PROJECTS = [
    "client",
    "common",
    "debugging",
    "postgresql",
    "server",
    "web",
]


TOP_LEVEL_CODES = {"I001"}


class CI:
    PROJECTS = PROJECTS

    @cached_property
    def flake8(self):
        return Flake8(self.root)

    @cached_property
    def git(self):
        return Git()

    @cached_property
    def root(self):
        return self.git.toplevel

    @cached_property
    def ruff(self):
        return Ruff(self.root)
