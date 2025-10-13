from .lint import LintResults
from collections import defaultdict
from functools import cached_property
from pathlib import Path
import asyncio
import os
import re
import shutil
import subprocess
import weakref


try:
    import tomllib
except ImportError:
    import tomli as tomllib


def load_toml(p):
    with p.open("rb") as f:
        return tomllib.load(f)


class RuffConfig:
    tool_name = "ruff"

    def __init__(self, configs, name):
        self.configs = weakref.ref(configs)
        self.name = name

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r}>"

    @cached_property
    def _pyproject_toml(self):
        return load_toml(self.base / "pyproject.toml").get("tool", {}).get("ruff", {})

    @cached_property
    def base(self):
        base = self.configs().base
        if self.name is not None:
            base = base / self.name
        return base

    @cached_property
    def exclude(self):
        result = {
            ".bzr",
            ".direnv",
            ".eggs",
            ".git",
            ".git-rewrite",
            ".hg",
            ".mypy_cache",
            ".nox",
            ".pants.d",
            ".pytype",
            ".ruff_cache",
            ".svn",
            ".tox",
            ".venv",
            "__pypackages__",
            "_build",
            "buck-out",
            "dist",
            "node_modules",
            "venv",
        }
        lint_section = self.lint_section
        if exclude := lint_section.get("exclude", {}):
            result = exclude
        if extend_exclude := lint_section.get("extend-exclude", {}):
            result.update(extend_exclude)
        return result

    @cached_property
    def extend_ignore(self):
        if extend_ignore := frozenset(
            self.lint_section.get("extend-ignore", frozenset())
        ):
            return extend_ignore
        return frozenset()

    @cached_property
    def extend_select(self):
        if extend_select := frozenset(
            self.lint_section.get("extend-select", frozenset())
        ):
            return extend_select
        return frozenset()

    @cached_property
    def format_excludes(self):
        return {Path(p) for p in self.format_section.get("exclude", [])}

    @property
    def format_section(self):
        return self._pyproject_toml.get("format", {})

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
        results = set() if self.name is None else set(self.configs()[None].ignore)
        lint_section = self.lint_section
        if ignore := set(lint_section.get("ignore", set())):
            results = ignore
        if extend_ignore := self.extend_ignore:
            results.update(extend_ignore)
        return frozenset(results)

    @property
    def lint_section(self):
        return self._pyproject_toml.get("lint", {})

    @cached_property
    def per_file_ignores(self):
        results = (
            {} if self.name is None else dict(self.configs()[None].per_file_ignores)
        )
        lint_section = self.lint_section
        if per_file_ignores := lint_section.get("per-file-ignores", {}):
            results = per_file_ignores
        if extend_per_file_ignores := lint_section.get("extend-per-file-ignores", {}):
            results.update(
                {self.base / k: v for k, v in extend_per_file_ignores.items()}
            )
        return {k: frozenset(v) for k, v in results.items()}

    @cached_property
    def target_version(self):
        return self._pyproject_toml.get("target-version")

    @cached_property
    def target_version_args(self):
        if (target_version := self.target_version) is not None:
            return ["--config", f'target-version="{target_version}"']
        return []


class Ruff:
    def __init__(self, base):
        self.base = base
        self._projects = {}

    def __getitem__(self, name):
        if name not in self._projects:
            self._projects[name] = RuffConfig(self, name)
        return self._projects[name]

    async def _format_diff_ranges(self, diff):
        for fn, line_ranges in diff.ranges.items():
            path = Path(fn)
            if not path.exists():
                continue
            fn_lines = path.read_text().splitlines()
            for start, end in line_ranges:
                check_lines = fn_lines[start - 1 : end]
                yield (fn, (start, 1), (end, len(check_lines[-1]) + 1), check_lines)
            del fn_lines

    async def _format_range(self, fn, start, end):
        cmd = [
            self._ruff,
            "format",
            "--config",
            "ruff-strict.toml",
            "--force-exclude",
            "--check",
            "--diff",
            fn,
            "--range",
            f"{start[0]}:{start[1]}-{end[0]}:{end[1]}",
        ]
        p = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        (out, err) = await p.communicate()
        rc = await p.wait()
        if rc not in (0, 1):
            raise subprocess.CalledProcessError(rc, cmd, out, err)
        return None if not rc or not out else out.decode()

    async def _format_range_worker(self, queue, results, exceptions):
        while True:
            item = await queue.get()
            try:
                (fn, start, end, check_lines) = item
                result = await self._format_range(fn, start, end)
                if result is not None:
                    results.append((fn, start, end, result, check_lines))
            except Exception as e:  # noqa: BLE001
                exceptions.append(e)
            finally:
                queue.task_done()

    @cached_property
    def _pyproject_toml(self):
        return load_toml(self.base / "pyproject.toml").get("tool", {}).get("ruff", {})

    @cached_property
    def _ruff(self):
        return shutil.which("ruff")

    @cached_property
    def _strict(self):
        return load_toml(self.base / "ruff-strict.toml")

    def check_format_excludes(self, *projects):
        cmd = [
            self._ruff,
            "format",
            "-q",
            "--config",
            "ruff-strict.toml",
            "--force-exclude",
            "--check",
        ]
        result = subprocess.run(  # noqa: S603
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            text=True,
        )
        if (rc := result.returncode) not in (0, 1):
            raise subprocess.CalledProcessError(rc, cmd, result.stdout, result.stderr)
        paths = {p: self.base / p for p in projects if p is not None}
        paths[None] = self.base
        results = defaultdict(set)
        matcher = re.compile(r"^Would reformat: (?P<fn>.+)$")
        for line in result.stdout.splitlines():
            if (m := matcher.match(line)) is None:
                continue
            fn = self.base / m["fn"]
            for project, path in paths.items():
                if fn.is_relative_to(path):
                    results[project].add(fn.relative_to(path))
                    break
        for project_name in projects:
            project = self[project_name]
            would_format = results[project_name]
            for exclude in project.format_excludes:
                path = project.base / exclude
                if not path.exists():
                    yield f"Obsolete ruff format exclude for deleted {exclude} in {project.name}"
                elif exclude not in would_format:
                    yield f"Obsolete ruff format exclude for {exclude} in {project.name}"

    async def format_diffs(self, diff):
        N_WORKERS = 10
        queue = asyncio.Queue(N_WORKERS)
        exceptions = []
        results = []
        workers = [
            asyncio.create_task(self._format_range_worker(queue, results, exceptions))
            for _ in range(N_WORKERS)
        ]
        async for fn, start, end, check_lines in self._format_diff_ranges(diff):
            await queue.put((fn, start, end, check_lines))
        await queue.join()
        for worker in workers:
            worker.cancel()
        del workers
        del queue
        for e in exceptions:
            if isinstance(e, subprocess.CalledProcessError):
                print(f"{e!r}")  # noqa: T201
            raise e
        format_diffs = set()
        for _, start, _, format_diff, check_lines in sorted(results):
            if format_diff not in format_diffs:
                yield start[0], format_diff, check_lines
                format_diffs.add(format_diff)

    async def strict_output(self, *projects, color=False):
        results = defaultdict(list)
        for project in projects:
            path = self.base if project is None else self.base / project
            cmd = [
                self._ruff,
                "check",
                "--config",
                "ruff-strict.toml",
                "--output-format",
                "concise",
                *self[project].target_version_args,
                path,
            ]
            env = ({"FORCE_COLOR": "1"} | os.environ) if color else None
            p = await asyncio.create_subprocess_exec(
                *cmd, env=env, stdout=asyncio.subprocess.PIPE
            )
            (out, err) = await asyncio.wait_for(p.communicate(), timeout=120)
            rc = await asyncio.wait_for(p.wait(), timeout=120)
            if rc not in (0, 1):
                raise subprocess.CalledProcessError(rc, cmd, out, err)
            for result in LintResults(self.base, self[project], out.decode()).results:
                if result["path"].is_relative_to(path):
                    results[project].append(result["raw_line"])
        return {
            p: LintResults(self.base, self[p], "\n".join(lines))
            for p, lines in results.items()
        }
