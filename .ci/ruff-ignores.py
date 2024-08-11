# noqa: INP001
from pathlib import Path
import sys


try:
    import tomllib
except ImportError:
    import tomli as tomllib


with Path(sys.argv[1]).joinpath("pyproject.toml").open("rb") as f:
    configured_ignores = tomllib.load(f)['tool']['ruff']['lint']['extend-ignore']
ignores = sorted(set(configured_ignores).difference((
    'I001',
)))
print(' '.join(ignores))  # noqa: T201
