import py
import functools
import operator

def propmapping(name, type=None):
    if type is None:
        def fget(self):
            return self._mapping.get(name)
    else:
        def fget(self):
            x = self._mapping.get(name)
            if x is not None:
                x = type(x)
            return x
    fget.__name__ = name
    return property(fget)


def canraise(Error):
    def wrap(func):
        func.Error = Error
        return func
    return wrap

class lazydecorator:
    """ lazydecorator (c) holger krekel, 2013, License: MIT """
    FunctionType = type(lambda: None)

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

    def discover_and_call(self, obj, dec):
        decitems = []
        for name in dir(obj):
            func_orig = func = getattr(obj, name)
            if not isinstance(func, self.FunctionType):
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
        for num, func_orig, siglist in decitems:
            for args, kwargs in siglist:
                newfunc = dec(*args, **kwargs)(func_orig)
                assert newfunc == func_orig

def cached_property(f):
    """returns a cached property that is calculated by function f"""
    def get(self):
        try:
            return self._property_cache[f]
        except AttributeError:
            self._property_cache = {}
            x = self._property_cache[f] = f(self)
            return x
        except KeyError:
            x = self._property_cache[f] = f(self)
            return x
    def set(self, val):
        propcache = self.__dict__.setdefault("_property_cache", {})
        propcache[f] = val

    return property(get, set)

class CompareMixin(object):
    def _cmp(self, other, op):
        try:
            return op(self.cmpval, other.cmpval)
        except AttributeError:
            raise NotImplemented
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

def gen_comparisons_with_key(cls, key):
    for name, op in (("lt", "<"), ("le", "<="), ("eq", "=="), ("ne", "!="),
                     ("ge", ">="), ("gt", ">")):
        d = {}
        fullname = "__" + name + "__"
        py.builtin.exec_(py.code.Source("""
            def %s(self, other):
                try:
                    return self.%s %s other.%s
                except AttributeError:
                    raise NotImplemented
        """ %(fullname, key, op, key)).compile(), d)
        setattr(cls, fullname, d[fullname])
