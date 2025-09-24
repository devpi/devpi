#!/usr/bin/env python
# ruff: noqa: T201

from ci_helpers import CI
from collections import defaultdict
from io import StringIO
from match_diff_lines import parse_unified_diff
import argparse
import asyncio
import subprocess


def ruff_format_diff(ruff):
    cmd = [
        ruff._ruff,
        "format",
        "-q",
        "--config",
        "ruff-strict.toml",
        "--force-exclude",
        "--diff",
    ]
    result = subprocess.run(  # noqa: S603
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        text=True,
    )
    return parse_unified_diff(StringIO(result.stdout))


async def main(args):
    ci = CI()
    tasks = []
    if not args.no_flake8:
        tasks.append(
            asyncio.create_task(ci.flake8.strict_output(*ci.PROJECTS, color=True))
        )
    if not args.no_format:
        for fn, line_nums in ruff_format_diff(ci.ruff).items():
            if len(line_nums) < 10:
                print(f"{fn} has few changes before fully formatted")
    if not args.no_ruff:
        tasks.append(
            asyncio.create_task(ci.ruff.strict_output(".ci", *ci.PROJECTS, color=True))
        )
    results = defaultdict(list)
    for _results in asyncio.as_completed(tasks):
        for linter_result in (await _results).values():
            for result in linter_result.results:
                results[result["rule"]].append(result["raw_line"])
    total = 0
    out = []
    for result in sorted(results.values(), key=len):
        out.extend(result)
        total = total + len(result)
        if total > 15:
            break
    print("\n".join(sorted(out)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-flake8", action="store_true")
    parser.add_argument("--no-format", action="store_true")
    parser.add_argument("--no-ruff", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
