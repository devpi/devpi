#!/usr/bin/env python
from pathlib import Path
import os
import subprocess


try:
    import tomllib
except ImportError:
    import tomli as tomllib


def main():
    base = Path().absolute()
    package_target_version = {}
    for pyproject_path in base.glob("*/pyproject.toml"):
        with pyproject_path.open("rb") as f:
            config = tomllib.load(f)
        package_target_version[pyproject_path.parent.name] = config["tool"]["ruff"].get(
            "target-version"
        )
    lines = []
    for package, target_version in package_target_version.items():
        args = [
            "ruff",
            "check",
            "--config",
            "ruff-strict.toml",
            "--output-format",
            "concise",
        ]
        if target_version:
            args.extend(
                [
                    "--config",
                    f'target-version="{target_version}"',
                ]
            )
        lines.extend(
            subprocess.run(  # noqa: S603
                [*args, package],
                check=False,
                env={"FORCE_COLOR": "1"} | os.environ,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout.splitlines()
        )
    results = {}
    for line in lines:
        if ":" not in line:
            continue
        code = line.split(None, 2)[1:2]
        if not code:
            continue
        results.setdefault(code[0], []).append(line)
    total = 0
    out = []
    for result in sorted(results.values(), key=len):
        out.extend(result)
        total = total + len(result)
        if total > 15:
            break
    print("\n".join(sorted(out)))  # noqa: T201


if __name__ == "__main__":
    main()
