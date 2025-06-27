# noqa: INP001
from ci_helpers import CI
import asyncio
import sys


async def main():
    ci = CI()
    project = sys.argv[1]
    lint_section = ci.ruff[project].lint_section
    extend_select = set(lint_section.get("extend-select", set()))
    extend_ignore = set(lint_section.get("extend-ignore", []))
    configured_ignores = {
        x for x in extend_ignore if x.strip("0123456789") not in extend_select
    }
    ignores = sorted(configured_ignores.difference({"I001"}))
    print(" ".join(ignores))  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
