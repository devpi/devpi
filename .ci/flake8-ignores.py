# noqa: INP001
from configparser import RawConfigParser
from pathlib import Path
import sys


config = RawConfigParser()
configfile = Path(sys.argv[1]).joinpath(".flake8")
config.read(configfile)
config = {sk: dict(sv.items()) for sk, sv in config.items()}
ignores = set()
per_file_ignores = [v.split(':', 1)[1].split(',') for x in config['flake8'].get('per-file-ignores', '').splitlines() if (v := x.strip())]
for additional_ignores in per_file_ignores:
    ignores.update(additional_ignores)
print(' '.join(ignores))  # noqa: T201
