#!/usr/bin/env python
# ruff: noqa: T201

from ci_helpers import CI
from ci_helpers import TOP_LEVEL_CODES
from ci_helpers.lint import paths_for_per_file_ignores
from collections import defaultdict
import argparse
import asyncio
import sys


async def main(args):  # noqa: PLR0912
    ci = CI()
    failed = False
    all_python_files = ci.git.python_files
    full_python_diff = await ci.git.python_diff(args.commit or ci.git.fork_point)
    if args.verbose:
        if args.verbose > 1:
            print(full_python_diff)
        else:
            for fn, _ranges in sorted(full_python_diff.ranges.items()):
                ranges = ", ".join(f"{s}" if s == e else f"{s}-{e}" for s, e in _ranges)
                print(f"{fn}: {ranges}")
    if not args.no_format:
        async for start, format_diff, check_lines in ci.ruff.format_diffs(
            full_python_diff
        ):
            print(format_diff)
            if args.verbose:
                print("Triggered by:")
                width = len(f"{start + len(check_lines)}")
                print(
                    "\n".join(
                        f"{num:{width}}: {l}"
                        for num, l in enumerate(check_lines, start=start)
                    )
                )
                print()
            failed = True
        for msg in ci.ruff.check_format_excludes(None, *ci.PROJECTS):
            print(msg)
            failed = True
    flake8_results = (
        {} if args.no_flake8 else await ci.flake8.strict_output(*ci.PROJECTS)
    )
    ruff_results = await ci.ruff.strict_output(*ci.PROJECTS)
    results = sorted(
        (*flake8_results.items(), *ruff_results.items()), key=lambda i: i[0] or ""
    )
    for project, result in results:
        rules = result.rules
        linter = result.linter()
        ignore = linter.ignore
        paths = paths_for_per_file_ignores(all_python_files, linter)
        per_file_ignores = linter.per_file_ignores
        seen = set()
        for line in result.match_lines(full_python_diff):
            # handle top level rules extra
            file_ignores = ignore | per_file_ignores.get(line.info["path"], set())
            if (rule := line.info["rule"]) in TOP_LEVEL_CODES and rule in file_ignores:
                continue
            seen.add(line)
            print(line.rstrip())
            failed = True
        path_ignores = defaultdict(set)
        for fn, found_paths in paths.items():
            deleted = False
            obsolete_rules = per_file_ignores[fn]
            for path in found_paths:
                path_ignores[path].update(per_file_ignores.get(fn, set()))
                if not path.exists():
                    deleted = True
                elif path in rules:
                    obsolete_rules = obsolete_rules - rules[path]
            if deleted:
                print(
                    f"Obsolete {linter.tool_name} per-file-ignore for deleted {fn} in {project}"
                )
                failed = True
            elif obsolete_rules == per_file_ignores[fn]:
                print(
                    f"Obsolete {linter.tool_name} per-file-ignore for {fn} in {project}"
                )
                failed = True
            elif obsolete_rules:
                print(
                    f"Obsolete {linter.tool_name} rules {', '.join(sorted(obsolete_rules))} in per-file-ignore for {fn} in {project}"
                )
                failed = True
        for info in result.results:
            line = info["line"]
            rule = info["rule"]
            if line in seen or rule in ignore or rule in path_ignores[info["path"]]:
                continue
            print(line.rstrip())
            failed = True
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("commit", nargs="?", type=str, default=None)
    parser.add_argument("--no-flake8", action="store_true")
    parser.add_argument("--no-format", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    asyncio.run(main(args))
