import traceback


class LazyExceptionFormatter:
    __slots__ = ('e',)

    def __init__(self, e):
        self.e = e

    def __str__(self):
        return ''.join(traceback.format_exception(
            self.e.__class__, self.e, self.e.__traceback__)).strip()


class LazyExceptionOnlyFormatter:
    __slots__ = ('e',)

    def __init__(self, e):
        self.e = e

    def __str__(self):
        return ''.join(traceback.format_exception_only(
            self.e.__class__, self.e)).strip()


def lazy_format_exception(e):
    return LazyExceptionFormatter(e)


def lazy_format_exception_only(e):
    return LazyExceptionOnlyFormatter(e)
