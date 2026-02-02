import traceback


class LazyExceptionFormatter:
    __slots__ = ('e',)

    def __init__(self, e):
        self.e = e

    def __str__(self):
        return format_exception(self.e)


class LazyExceptionOnlyFormatter:
    __slots__ = ('e',)

    def __init__(self, e):
        self.e = e

    def __str__(self):
        return format_exception_only(self.e)


def format_exception(e):
    return "".join(traceback.format_exception(e.__class__, e, e.__traceback__)).strip()


def format_exception_only(e):
    return "".join(traceback.format_exception_only(e.__class__, e)).strip()


def lazy_format_exception(e):
    return LazyExceptionFormatter(e)


def lazy_format_exception_only(e):
    return LazyExceptionOnlyFormatter(e)
