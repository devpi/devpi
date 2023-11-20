class _absent:
    def __repr__(self):
        return '<absent>'


absent = _absent()


class _deleted:
    def __repr__(self):
        return '<deleted>'


deleted = _deleted()
