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
from types import FunctionType

class lazydecorator:
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
