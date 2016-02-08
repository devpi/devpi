from __future__ import unicode_literals

import hashlib
import operator
import py

FunctionType = py.std.types.FunctionType

# re-introduced for 2.0 series but not used anymore
def propmapping(name, convert=None):
    if convert is None:
        def fget(self):
            return self._mapping.get(name)
    else:
        def fget(self):
            x = self._mapping.get(name)
            if x is not None:
                x = convert(x)
            return x
    fget.__name__ = name
    return property(fget)

def canraise(Error):
    def wrap(func):
        func.Error = Error
        return func
    return wrap


def cached_property(f):
    """returns a cached property that is calculated by function f"""
    def get(self):
        try:
            return self._property_cache[f]
        except AttributeError:
            self._property_cache = {}
        except KeyError:
            pass
        x = self._property_cache[f] = f(self)
        return x

    def set(self, val):
        propcache = self.__dict__.setdefault("_property_cache", {})
        propcache[f] = val
    return property(get, set)

class CompareMixin(object):
    def _cmp(self, other, op):
        return op(self.cmpval, other.cmpval)

    def __lt__(self, other):
        return self._cmp(other, operator.lt)
    def __le__(self, other):
        return self._cmp(other, operator.le)
    def __eq__(self, other):
        return self._cmp(other, operator.eq)
    def __ne__(self, other):
        return self._cmp(other, operator.ne)
    def __ge__(self, other):
        return self._cmp(other, operator.ge)
    def __gt__(self, other):
        return self._cmp(other, operator.gt)


class lazydecorator:
    """
    lazy decorators:  remove global state from your app, e.g. Bottle and Flask.

    A lazy decorator takes the place of another decorator, but just memoizes
    decoration parameters and lets you choose when to apply the actual decorator.   This means that you are not tied to apply decorators like the typical
    flask/bottle ``@app.route("/index")`` at import time and thus don't
    need to create a global ``app`` object.

    Example usage in a module.py:

        from lazydecorator import lazydecorator

        route = lazydecorator()

        class MyServer:
            @route("/index")
            def index(self):
                pass

    The lazydecorator "route" instance returns the same ``index`` function it
    receives but sets an attribute to remember the ``("/index")`` parameter.
    Later, after importing the ``module`` you can then apply your  ``@app.route``
    decorator like this::

        def create_app():
            app = Bottle()
            import module
            myserver = module.MyServer()
            module.route.discover_and_call(myserver, app.route)
            # The app.route decorator is called with the bound
            # ``myserver.index`` method

    order of registrations is preserved.

    (c) holger krekel, 2013, License: MIT
    """
    def __init__(self):
        self.attrname = "_" + hex(id(self))
        self.num = 0

    def __call__(self, *args, **kwargs):
        def decorate(func):
            try:
                num, siglist = getattr(func, self.attrname)
            except AttributeError:
                siglist = []
                func.__dict__[self.attrname] = (self.num, siglist)
                self.num += 1
            siglist.append((args, kwargs))
            return func
        return decorate

    def discover(self, obj):
        decitems = []
        if isinstance(obj, dict):
            def iter():
                for name in obj:
                    yield name, obj[name]
        else:
            def iter():
                for name in dir(obj):
                    yield name, getattr(obj, name)
        for name, func in iter():
            func_orig = func
            if not isinstance(func, FunctionType):
                try:
                    func = func.__func__
                except AttributeError:
                    continue
            try:
                num, siglist = getattr(func, self.attrname)
            except AttributeError:
                continue
            decitems.append((num, func_orig, siglist))
        decitems.sort()
        l = []
        for num, func_orig, siglist in decitems:
            for args, kwargs in siglist:
                l.append((func_orig, args, kwargs))
        return l

    def discover_and_call(self, obj, dec):
        for func, args, kwargs in self.discover(obj):
            newfunc = dec(*args, **kwargs)(func)
            assert newfunc == func


def ensure_unicode(x):
    if py.builtin._istext(x):
        return x
    return py.builtin._totext(x, "utf8")


def parse_hash_spec(fragment):
    """ Return (hashtype, hash_value) from parsing a given X=Y fragment.
    X must be a supported algorithm by the python hashlib module."""
    parts = fragment.split("=", 1)
    if len(parts) == 2:
        algoname, hash_value = parts
        algo = getattr(hashlib, algoname, None)
        if algo is not None:
            return algo, hash_value
    return None, None
