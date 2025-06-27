#!/usr/bin/env python
# ruff: noqa: T201

from ci_helpers import CI
import asyncio
import sys


async def main():
    ci = CI()
    project = sys.argv[1]
    for msg in ci.ruff.check_format_excludes(project):
        print(msg)


if __name__ == "__main__":
    asyncio.run(main())
