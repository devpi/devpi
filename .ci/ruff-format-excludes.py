# noqa: INP001
from pathlib import Path
import subprocess
import sys


try:
    import tomllib
except ImportError:
    import tomli as tomllib


base_path = Path(sys.argv[1])
with base_path.joinpath("pyproject.toml").open("rb") as f:
    format_section = tomllib.load(f)["tool"]["ruff"]["format"]
excludes = format_section.get("exclude", ())
for exclude in excludes:
    if not (path := base_path / exclude).exists():
        print("Obsolete ruff format exclude for deleted", path)  # noqa: T201
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ruff",
            "format",
            "-q",
            "--config",
            "ruff-strict.toml",
            "--force-exclude",
            "--check",
            path,
        ],
        check=False,
        stdout=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        print("Obsolete ruff format exclude for", path)  # noqa: T201
