# noqa: INP001
from match_diff_lines import parse_unified_diff
from pathlib import Path
import itertools
import subprocess
import sys


def ranges(numbers):
    for _a, _b in itertools.groupby(
        enumerate(sorted(numbers)), lambda pair: pair[1] - pair[0]
    ):
        b = list(_b)
        yield b[0][1], b[-1][1]


def main():
    with Path(sys.argv[1]).open() as f:
        diff = parse_unified_diff(f)
    for path, lines in diff.items():
        diffs = set()
        if not lines:
            continue
        if not Path(path).exists():
            continue
        for start, end in ranges(lines):
            line_range = f"{start}:1-{end + 1}:1"
            result = subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "ruff",
                    "format",
                    "-q",
                    "--config",
                    "ruff-strict.toml",
                    "--force-exclude",
                    "--check",
                    "--diff",
                    path,
                    "--range",
                    line_range,
                ],
                check=False,
                stdout=subprocess.PIPE,
                text=True,
            )
            out = result.stdout
            if not result.returncode or not out:
                continue
            if out not in diffs:
                print(out)  # noqa: T201
                diffs.add(out)


if __name__ == "__main__":
    main()
