# noqa: INP001
from pathlib import Path
import sys


try:
    import tomllib
except ImportError:
    import tomli as tomllib


with Path(sys.argv[1]).joinpath("pyproject.toml").open("rb") as f:
    lint_section = tomllib.load(f)["tool"]["ruff"]["lint"]
extend_select = set(lint_section.get("extend-select", ()))
configured_ignores = [
    x
    for x in lint_section.get("extend-ignore", [])
    if x.strip("0123456789") not in extend_select
]
ignores = sorted(set(configured_ignores).difference((
    'I001',
)))
print(' '.join(ignores))  # noqa: T201
