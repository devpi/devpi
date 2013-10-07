from devpi_common.types  import lazydecorator

pytest_plugins = "pytester"

def test_simpler():
    dec = lazydecorator()
    class A:
        @dec(5)
        @dec(1, kw=3)
        def f(self):
            pass

    a = A()

    l2 = []
    def anotherdec(arg, kw=None):
        def wrapped(func):
            l2.append((func, arg, kw))
            return func
        return wrapped

    dec.discover_and_call(a, anotherdec)
    assert len(l2) == 2
    assert l2[0] == (a.f, 1, 3)
    assert l2[1] == (a.f, 5, None)

def test_simpler_dict():
    dec = lazydecorator()

    @dec()
    def f():
        pass
    @dec(x=1)
    def g():
        pass
    d = {"f": f, "g": g, "something": lambda: None}
    l = dec.discover(d)
    assert len(l) == 2
    assert l[0] == (f, (), {})
    assert l[1] == (g, (), dict(x=1))

def test_multi():
    dec = lazydecorator()
    class A:
        @dec(1)
        def c(self):
            pass
        @dec(2)
        def b(self):
            pass
        @dec(3)
        def a(self):
            pass

    a = A()

    l2 = []
    def anotherdec(arg, kw=None):
        def wrapped(func):
            l2.append((func, arg))
            return func
        return wrapped

    dec.discover_and_call(a, anotherdec)
    assert len(l2) == 3
    assert l2[0] == (a.c, 1)
    assert l2[1] == (a.b, 2)
    assert l2[2] == (a.a, 3)

def test_simpler_mod(testdir):
    p = testdir.makepyfile("""
        from devpi_common.types import lazydecorator

        dec = lazydecorator()
        @dec("world")
        @dec("hello")
        def f():
            pass
    """)
    mod = p.pyimport()

    l = []
    def anotherdec(arg):
        def wrapped(func):
            l.append((arg, func))
            return func
        return wrapped
    mod.dec.discover_and_call(mod, anotherdec)
    assert len(l) == 2
    assert l == [("hello", mod.f), ("world", mod.f)]

