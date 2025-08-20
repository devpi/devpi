from .lint import LintResults
from configparser import RawConfigParser
from functools import cached_property
import asyncio
import shutil
import weakref


class Flake8Config:
    tool_name = "flake8"

    def __init__(self, configs, name):
        self.configs = weakref.ref(configs)
        self.name = name

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r}>"

    @cached_property
    def _flake8(self):
        config = RawConfigParser()
        config.read(self.base / ".flake8")
        return config

    @cached_property
    def base(self):
        base = self.configs().base
        if self.name is not None:
            base = base / self.name
        return base

    @cached_property
    def exclude(self):
        result = {
            ".svn",
            "CVS",
            ".bzr",
            ".hg",
            ".git",
            "__pycache__",
            ".tox",
            ".nox",
            ".eggs",
            "*.egg",
        }
        if exclude := {
            e
            for _e in self._flake8.get("flake8", "exclude", fallback="").split(",")
            if (e := _e.strip())
        }:
            result = exclude
        if extend_exclude := {
            e
            for _e in self._flake8.get("flake8", "extend-exclude", fallback="").split(
                ","
            )
            if (e := _e.strip())
        }:
            result.update(extend_exclude)
        return result

    def get_python_files(self, python_files):
        exclude = self.exclude
        root = self.base
        return {
            p
            for p in python_files
            if p.is_relative_to(root) and not exclude.intersection(p.parts)
        }

    @cached_property
    def ignore(self):
        return frozenset(sorted(self._flake8.get("flake8", "ignore").split(",")))

    @cached_property
    def ignore_args(self):
        if (ignore := self.ignore) is not None:
            return ["--ignore", ",".join(ignore)]
        return []

    @cached_property
    def per_file_ignores(self):
        results = {}
        for item in self._flake8.get(
            "flake8", "per-file-ignores", fallback=""
        ).splitlines():
            if not (v := item.strip()):
                continue
            (k, p, i) = v.partition(":")
            if not p:
                continue
            results[k.strip()] = frozenset(x.strip() for x in i.split(","))
        return results


class Flake8:
    def __init__(self, base):
        self.base = base
        self._projects = {}

    def __getitem__(self, name):
        if name not in self._projects:
            self._projects[name] = Flake8Config(self, name)
        return self._projects[name]

    @cached_property
    def _flake8(self):
        return shutil.which("flake8")

    async def _strict_output(self, base, project, *, color=False):
        color_args = ["--color", "always"] if color else []
        cmd = [
            self._flake8,
            *color_args,
            *self[project].ignore_args,
            project,
        ]
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
        (out, err) = await p.communicate()
        await p.wait()
        return LintResults(base, self[project], out.decode())

    async def strict_output(self, *projects, color=False):
        results = await asyncio.gather(
            *(self._strict_output(self.base, p, color=color) for p in projects)
        )
        return dict(zip(projects, results))
