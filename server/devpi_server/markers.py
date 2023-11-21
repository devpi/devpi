from __future__ import annotations


class Absent:
    def __repr__(self) -> str:
        return '<absent>'


absent = Absent()


class Deleted:
    def __repr__(self) -> str:
        return '<deleted>'


deleted = Deleted()
