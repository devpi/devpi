"""
PluginManager, basic initialization and tracing.
"""
import sys, os
import inspect
import py

DECLKEY = "devpihookdecl"
IMPLKEY = "devpihookimpl"

def hookdecl(firstresult=False):
    """ decorator for declaring new hooks. """
    markinfo = dict(firstresult=firstresult)
    def mark(func):
        assert not hasattr(func, DECLKEY)
        setattr(func, DECLKEY, markinfo)
        return func
    return mark

def hookimpl(tryfirst=False, trylast=False):
    """ decorator for marking a hook implementation function. """
    markinfo = dict(tryfirst=tryfirst, trylast=trylast)
    def mark(func):
        setattr(func, IMPLKEY, markinfo)
        return func
    return mark

class TagTracer:
    def __init__(self):
        self._tag2proc = {}
        self.writer = None
        self.indent = 0

    def get(self, name):
        return TagTracerSub(self, (name,))

    def format_message(self, tags, args):
        if isinstance(args[-1], dict):
            extra = args[-1]
            args = args[:-1]
        else:
            extra = {}

        content = " ".join(map(str, args))
        indent = "  " * self.indent

        lines = [
            "%s%s [%s]\n" %(indent, content, ":".join(tags))
        ]

        for name, value in extra.items():
            lines.append("%s    %s: %s\n" % (indent, name, value))
        return lines

    def processmessage(self, tags, args):
        if self.writer is not None and args:
            lines = self.format_message(tags, args)
            self.writer(''.join(lines))
        try:
            self._tag2proc[tags](tags, args)
        except KeyError:
            pass

    def setwriter(self, writer):
        self.writer = writer

    def setprocessor(self, tags, processor):
        if isinstance(tags, str):
            tags = tuple(tags.split(":"))
        else:
            assert isinstance(tags, tuple)
        self._tag2proc[tags] = processor

class TagTracerSub:
    def __init__(self, root, tags):
        self.root = root
        self.tags = tags
    def __call__(self, *args):
        self.root.processmessage(self.tags, args)
    def setmyprocessor(self, processor):
        self.root.setprocessor(self.tags, processor)
    def get(self, name):
        return self.__class__(self.root, self.tags + (name,))


class PluginManager(object):
    def __init__(self, hookspec):
        self._name2plugin = {}
        self.trace = TagTracer().get("pm")
        #self.trace.root.setwriter(sys.stdout.write)
        #self._plugin_distinfo = []
        self.hook = HookRelay([hookspec], pm=self)
        self.register(self)

    def register(self, plugin, name=None):
        if self._name2plugin.get(name, None) == -1:
            return
        name = name or getattr(plugin, '__name__', str(id(plugin)))
        if self.isregistered(plugin, name):
            raise ValueError("Plugin already registered: %s=%s" %(name, plugin))
        self.trace("registering", name, plugin)
        self.hook.addhookimpl(plugin)
        self._name2plugin[name] = plugin
        return True

    def unregister(self, plugin=None, name=None):
        if plugin is None:
            plugin = self.getplugin(name=name)
        #self.hook.pytest_plugin_unregistered(plugin=plugin)
        for name, value in list(self._name2plugin.items()):
            if value == plugin:
                del self._name2plugin[name]
        self.hook.removehookimpl(plugin)

    def isregistered(self, plugin, name=None):
        if self.getplugin(name) is not None:
            return True
        for val in self._name2plugin.values():
            if plugin == val:
                return True

    def addhooks(self, spec):
        self.hook.addhooks(spec)

    def hasplugin(self, name):
        return bool(self.getplugin(name))

    def getplugin(self, name):
        if name is None:
            return None
        try:
            return self._name2plugin[name]
        except KeyError:
            return self._name2plugin.get("_pytest." + name, None)


    def XXXconsider_setuptools_entrypoints(self):
        try:
            from pkg_resources import iter_entry_points, DistributionNotFound
        except ImportError:
            return # XXX issue a warning
        for ep in iter_entry_points('pytest11'):
            name = ep.name
            if name.startswith("pytest_"):
                name = name[7:]
            if ep.name in self._name2plugin or name in self._name2plugin:
                continue
            try:
                plugin = ep.load()
            except DistributionNotFound:
                continue
            self._plugin_distinfo.append((ep.dist, plugin))
            self.register(plugin, name=name)

    def consider_preparse(self, args):
        for opt1,opt2 in zip(args, args[1:]):
            if opt1 == "-p":
                self.consider_pluginarg(opt2)

    def consider_pluginarg(self, arg):
        if arg.startswith("no:"):
            name = arg[3:]
            if self.getplugin(name) is not None:
                self.unregister(None, name=name)
            self._name2plugin[name] = -1
        else:
            if self.getplugin(arg) is None:
                self.import_plugin(arg)


    def import_plugin(self, modname):
        assert isinstance(modname, str)
        if self.getplugin(modname) is not None:
            return
        try:
            #self.trace("importing", modname)
            mod = importplugin(modname)
        except KeyboardInterrupt:
            raise
        else:
            self.register(mod, modname)

    @hookimpl()
    def plugin_registered(self, plugin):
        import pytest
        dic = self.call_plugin(plugin, "pytest_namespace", {}) or {}
        if dic:
            self._setns(pytest, dic)
        if hasattr(self, '_config'):
            self.call_plugin(plugin, "pytest_addoption",
                {'parser': self._config._parser})
            self.call_plugin(plugin, "pytest_configure",
                {'config': self._config})


    def call_plugin(self, plugin, methname, kwargs):
        return MultiCall(methods=[getattr(plugin, methname)],
                kwargs=kwargs, firstresult=True).execute()


def importplugin(importspec):
    name = importspec
    try:
        mod = "devpi_server." + name
        __import__(mod)
        return sys.modules[mod]
    except ImportError:
        #e = py.std.sys.exc_info()[1]
        #if str(e).find(name) == -1:
        #    raise
        pass #
    try:
        __import__(importspec)
    except ImportError:
        raise ImportError(importspec)
    return sys.modules[importspec]

class MultiCall:
    """ execute a call into multiple python functions/methods. """
    def __init__(self, methods, kwargs, firstresult=False):
        self.methods = list(methods)
        self.kwargs = kwargs
        self.results = []
        self.firstresult = firstresult

    def __repr__(self):
        status = "%d results, %d meths" % (len(self.results), len(self.methods))
        return "<MultiCall %s, kwargs=%r>" %(status, self.kwargs)

    def execute(self):
        while self.methods:
            method = self.methods.pop()
            kwargs = self.getkwargs(method)
            #print "calling", method.__module__, method
            res = method(**kwargs)
            if res is not None:
                self.results.append(res)
                if self.firstresult:
                    return res
        if not self.firstresult:
            return self.results

    def getkwargs(self, method):
        kwargs = {}
        for argname in varnames(method):
            try:
                kwargs[argname] = self.kwargs[argname]
            except KeyError:
                if argname == "__multicall__":
                    kwargs[argname] = self
        return kwargs

def varnames(func):
    try:
        return func._varnames
    except AttributeError:
        pass
    if not inspect.isfunction(func) and not inspect.ismethod(func):
        func = getattr(func, '__call__', func)
    ismethod = inspect.ismethod(func)
    rawcode = py.code.getrawcode(func)
    try:
        x = rawcode.co_varnames[ismethod:rawcode.co_argcount]
    except AttributeError:
        x = ()
    py.builtin._getfuncdict(func)['_varnames'] = x
    return x

class HookRelay:
    def __init__(self, hookspecs, pm):
        if not isinstance(hookspecs, list):
            hookspecs = [hookspecs]
        self._hookspecs = []
        self._pm = pm
        self.trace = pm.trace.root.get("hook")
        for hookspec in hookspecs:
            self.addhooks(hookspec)

    def addhooks(self, hookspecs):
        self._hookspecs.append(hookspecs)
        added = False
        for name, method in vars(hookspecs).items():
            decl = getattr(method, DECLKEY, None)
            if decl is not None:
                hc = HookCaller(self, name, decl)
                setattr(self, name, hc)
                added = True
                #print ("setting new hook", name)
        if not added:
            raise ValueError("did not find new hooks in %r" %(
                hookspecs,))

    def addhookimpl(self, plugin):
        for name, method in vars(plugin).items():
            impl = getattr(method, IMPLKEY, None)
            if impl is not None:
                self.trace("registering", method)
                hookcaller = getattr(self, method.__name__, None)
                if hookcaller is None:
                    raise ValueError("undeclared hook: %s" %(method))
                hookcaller.addmethod(method, impl)

    def removehookimpl(self, plugin):
        for name, method in vars(plugin).items():
            impl = getattr(method, IMPLKEY, None)
            if impl is not None:
                hookcaller = getattr(self, method.__name__)
                hookcaller.removemethod(method)


class HookCaller:
    def __init__(self, hookrelay, name, decl):
        self.hookrelay = hookrelay
        self.methods = []
        self.name = name
        self.firstresult = decl["firstresult"]
        self.trace = self.hookrelay.trace

    def removemethod(self, method):
        self.methods.remove(method)

    def addmethod(self, method, impl):
        if impl["tryfirst"]:
            self.methods.append(method)
        elif impl["trylast"]:
            self.methods.insert(0, method)
        else:
            i = 0
            for i in range(0, len(self.methods)):
                if getattr(self.methods[i], IMPLKEY)["trylast"]:
                    continue
                break
            self.methods.insert(i, method)

    def __repr__(self):
        return "<HookCaller %r>" %(self.name,)

    def __call__(self, **kwargs):
        return self._docall(self.methods, kwargs)

    def _docall(self, methods, kwargs):
        self.trace(self.name, kwargs)
        self.trace.root.indent += 1
        mc = MultiCall(methods, kwargs, firstresult=self.firstresult)
        try:
            res = mc.execute()
            if res:
                self.trace("finish", self.name, "-->", res)
        finally:
            self.trace.root.indent -= 1
        return res
