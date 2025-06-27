#!/usr/bin/env python
# ruff: noqa: T201

from ci_helpers import CI
import asyncio
import sys


async def main():
    ci = CI()
    project = sys.argv[1]
    flake8 = ci.flake8[project]
    ignores = {i for c in flake8.per_file_ignores.values() for i in c}
    print(" ".join(ignores))


if __name__ == "__main__":
    asyncio.run(main())
