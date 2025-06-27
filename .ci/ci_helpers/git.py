# ruff: noqa: S603

from functools import cached_property
from io import StringIO
from match_diff_lines import parse_unified_diff
from pathlib import Path
import asyncio
import itertools
import shutil
import subprocess


def ranges(numbers):
    for _a, _b in itertools.groupby(
        enumerate(sorted(numbers)), lambda pair: pair[1] - pair[0]
    ):
        b = list(_b)
        yield b[0][1], b[-1][1]


class Diff(str):
    __slots__ = ("_parsed_diff", "_ranges")

    @property
    def parsed_diff(self):
        if not hasattr(self, "_parsed_diff"):
            self._parsed_diff = parse_unified_diff(StringIO(self))
        return self._parsed_diff

    @property
    def ranges(self):
        if not hasattr(self, "_ranges"):
            self._ranges = {
                fn: list(ranges(lines_nums))
                for fn, lines_nums in self.parsed_diff.items()
                if lines_nums
            }
        return self._ranges


class Git:
    @cached_property
    def _git(self):
        return shutil.which("git")

    @cached_property
    def commits_since_fork_point(self):
        return self.list_commits(self.fork_point, "HEAD")

    async def diff(self, *args):
        cmd = [self._git, "-C", self.toplevel, "diff", *args]
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
        (out, err) = await p.communicate()
        return_code = await p.wait()
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, cmd, out, err)
        return Diff(out.decode())

    @cached_property
    def fork_point(self):
        return self.merge_base("origin/main", "HEAD")

    def list_commits(self, start, end):
        output = subprocess.check_output(
            [self._git, "rev-list", "--ancestry-path", f"{start}..{end}"]
        )
        return list(reversed(output.decode().splitlines()))

    def merge_base(self, start, end):
        output = subprocess.check_output([self._git, "merge-base", start, end])
        return output.decode().strip()

    async def python_diff(self, commit):
        return await self.diff("--unified=0", "--relative", commit, "--", "*.py")

    @property
    def python_files(self):
        toplevel = self.toplevel
        output = subprocess.check_output(
            [
                self._git,
                "-C",
                toplevel,
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                "*.py",
            ]
        )
        return {toplevel / fn for fn in output.decode().splitlines()}

    @cached_property
    def toplevel(self):
        output = subprocess.check_output([self._git, "rev-parse", "--show-toplevel"])
        path = Path(output.decode().strip())
        assert path.exists()
        return path
