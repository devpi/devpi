try:
    import colorama
except ImportError:
    colorama = None
import os
import sys


_esctable = dict(
    bold='\x1b[1m', light='\x1b[2m', blink='\x1b[5m', invert='\x1b[7m',
    black='\x1b[30m', red='\x1b[31m', green='\x1b[32m', yellow='\x1b[33m',
    blue='\x1b[34m', purple='\x1b[35m', cyan='\x1b[36m', white='\x1b[37m',
    Black='\x1b[40m', Red='\x1b[41m', Green='\x1b[42m', Yellow='\x1b[43m',
    Blue='\x1b[44m', Purple='\x1b[45m', Cyan='\x1b[46m', White='\x1b[47m')


def isatty(fd):
    return hasattr(fd, 'isatty') and fd.isatty()


def should_do_markup(fd):
    if os.environ.get('PY_COLORS') == '1':
        return True
    if os.environ.get('PY_COLORS') == '0':
        return False
    if 'NO_COLOR' in os.environ:
        return False
    if os.environ.get('TERM') == 'dumb':
        return False
    if sys.platform.startswith('java') and os._name == 'nt':
        return False
    return isatty(fd)


class TerminalWriter:
    def __init__(self, fd=None):
        if fd is None:
            fd = sys.stdout
        if colorama is not None and isatty(fd):
            fd = colorama.AnsiToWin32(fd).stream
        self.fd = fd
        self.hasmarkup = should_do_markup(fd)

    def markup(self, text, **kwargs):
        esc = []
        for name in kwargs:
            if name not in _esctable:
                raise ValueError(f"unknown markup: {name!r}")
            if kwargs[name]:
                esc.append(_esctable[name])
        return ''.join((*esc, text, '\x1b[0m'))

    def write(self, msg, **kwargs):
        if not msg:
            return
        if self.hasmarkup and kwargs:
            msg = self.markup(msg, **kwargs)
        self.fd.write(msg)

    def line(self, s='', **kwargs):
        self.write(s, **kwargs)
        self.write('\n')
