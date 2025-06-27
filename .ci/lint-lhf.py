#!/usr/bin/env python
# ruff: noqa: T201

from ci_helpers import CI
from collections import defaultdict
import asyncio


async def main():
    ci = CI()
    ruff_results = await ci.ruff.strict_output(*ci.PROJECTS, color=True)
    results = defaultdict(list)
    for ruff_result in ruff_results.values():
        for result in ruff_result.results:
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
    asyncio.run(main())
