from collections import defaultdict
from match_diff_lines import match_lines
from pathlib import Path
from wcmatch.glob import GLOBSTAR
from wcmatch.glob import globfilter
import re
import weakref


ANSI_ESCAPE = re.compile(
    r"(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])"
)
LINT_REGEXP = re.compile(r"^\s*(?P<fn>.+?):\d+:\d+:\s(?P<rule>[^\s]+).*$")


class Line(str):
    __slots__ = ("info",)

    def __new__(cls, info):
        _info = dict(info)
        _line = _info.pop("line")
        line = super().__new__(cls, _line)
        line.info = _info
        return line


class LintResults(str):
    __slots__ = ("_results", "_rules", "base", "linter")

    def __new__(cls, base, linter, s):
        lintresult = super().__new__(cls, s)
        lintresult.base = base
        lintresult.linter = weakref.ref(linter)
        return lintresult

    def match_lines(self, diff):
        lines = (Line(line) for line in self.results)
        return match_lines(lines, diff.parsed_diff)

    @property
    def results(self):
        if not hasattr(self, "_results"):
            _results = self._results = []
            for num, raw_line in enumerate(self.splitlines(), start=1):
                line = ANSI_ESCAPE.sub("", raw_line)
                if not (m := LINT_REGEXP.match(line)):
                    continue
                _results.append(
                    dict(
                        line=line, num=num, path=self.base / m["fn"], raw_line=raw_line
                    )
                    | m.groupdict()
                )
        return self._results

    @property
    def rules(self):
        if not hasattr(self, "_rules"):
            _rules = self._rules = defaultdict(set)
            for m in self.results:
                _rules[m["path"]].add(m["rule"])
        return self._rules


def paths_for_per_file_ignores(all_python_files, linter):
    paths = defaultdict(set)
    python_files = linter.get_python_files(all_python_files)
    for fn in linter.per_file_ignores:
        path = fn if isinstance(fn, Path) else Path(fn)
        if not path.is_absolute():
            path = Path(f"**/{path}")
        found_paths = (
            [path]
            if path in python_files
            else globfilter(python_files, str(path), flags=GLOBSTAR)
        )
        if found_paths:
            paths[fn].update(found_paths)
        else:
            paths[fn].add(Path(fn))
    return paths
