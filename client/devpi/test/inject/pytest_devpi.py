import sys
import os
import py
import pytest

__version__ = '0.7'

def popenv_devpi(env):
    d = {}
    for name in ("posturl", "packageurl", "packagemd5"):
        try:
            d[name] = py.builtin._totext(env.pop("DEVPY_%s" % name.upper()),
                                         "UTF-8")
        except KeyError:
            return None
    return d

@pytest.mark.tryfirst
def pytest_configure(config):
    devpiinfo = popenv_devpi(os.environ)
    if devpiinfo is not None:
        if not config.option.resultlog:
            import tempfile
            name = tempfile.mktemp(prefix="resultlog-")
            config.option.resultlog = name
        config.option._devpiinfo = devpiinfo
        os.environ.pop("PYTEST_PLUGINS")

@pytest.mark.trylast
def pytest_unconfigure(config):
    devpiinfo = getattr(config.option, "_devpiinfo", None)
    if devpiinfo is None:
        return
    resultpath = config.option.resultlog
    if resultpath and not hasattr(config, 'slaveinput'):
        term = config.pluginmanager.getplugin("terminalreporter")
        f = py.std.codecs.open(str(resultpath), encoding="UTF8")
        try:
            location = postresultlog(resultfile=f, **devpiinfo)
        finally:
            f.close()
        print("POST results to %s -> %s " % (devpiinfo["posturl"],
                                             location))

def getplatforminfo():
    import sys, platform
    platformstring = platform.platform()
    platform = sys.platform
    pyversion = sys.version.replace("\n", "--")
    return dict(platformstring=platformstring, platform=platform,
                pyversion=pyversion)

class ProxyResponse(object):
    def __init__(self, val):
        self.status_code = val.code
        self._val = val

    def __repr__(self):
        return "<ProxyResponse status=%s>" % self.status_code

    def __getattr__(self, name):
        try:
            return getattr(self._val, name)
        except AttributeError:
            if name == "data":
                return self.read()
            raise

def httppost(url, data, headers):
    try:
        from urllib2 import Request, urlopen, HTTPError
    except ImportError:
        from urllib.request import Request, urlopen, HTTPError
    request = Request(url, data.encode("utf8"), headers=headers)
    try:
        return ProxyResponse(urlopen(request))
    except HTTPError:
        val = sys.exc_info()[1]
        return ProxyResponse(val)

def postresultlog(posturl, packageurl, packagemd5, resultfile):
    # XXX use streaming so that large result files are no problem
    res = ReprResultLog(packageurl, packagemd5, **getplatforminfo())
    try:
        res.parse_resultfile(resultfile)
    except FormatError:
        return
    data = res.dump()
    response = httppost(posturl, data, headers=
            {"CONTENT-TYPE": "text/plain"})
    if response.status_code != 201:
        return response
    return response.headers.get("location")

class FormatError(ValueError):
    """ wrong format of result log file. """

class ReprResultLog:
    def __init__(self, packageurl, packagemd5, platformstring,
                 platform, pyversion):
        self.packageurl = packageurl
        self.packagemd5 = packagemd5
        self.platformstring = platformstring
        self.platform = platform
        self.pyversion = pyversion
        self.entries = []

    def __eq__(self, other):
        names = list(self.__dict__)
        names.remove("entries")
        for name in names:
            if getattr(self, name) != getattr(other, name):
                return False
        for entry1, entry2 in zip(self.entries, other.entries):
            if (entry1.outcome != entry2.outcome or
                entry1.testid != entry2.testid or
                entry1.longrepr.rstrip() != entry2.longrepr.rstrip()):
                return False
        return True

    def _add(self, outcome, testid, longrepr=""):
        result = SingleResult(outcome, testid, longrepr)
        self.entries.append(result)

    def dump(self):
        l = ["packageurl: " + self.packageurl,
             "packagemd5: " + self.packagemd5,
             "platformstring: " + self.platformstring,
             "platform: " + self.platform,
             "pyversion: " + self.pyversion,
             ""]
        for entry in self.entries:
            l.append("%s %s" % (entry.outcome, entry.testid))
            if entry.longrepr:
                for line in entry.longrepr.split("\n"):
                    if line:
                        l.append(" " + line)
        return "\n".join(l)

    @classmethod
    def new_fromfile(cls, f):
        headers = {}

        while 1:
            line = f.readline()
            if not line.strip():
                break
            name, val = line.split(":", 1)
            headers[name] = val.strip()

        resultlog = cls(**headers)
        resultlog.parse_resultfile(f)
        return resultlog

    def parse_resultfile(self, f):
        line = f.readline()
        while line:
            line = line.rstrip()
            outcome = line[0]
            testid = line[2:]
            if outcome == ".":
                self._add(outcome, testid)
                line = f.readline()
            else:
                if not line[1] == " ":
                   raise FormatError(line)
                longrepr = []
                while 1:
                    line = f.readline()
                    if not line or line[0] != " ":
                        break
                    longrepr.append(line[1:])
                content = "\n".join(longrepr)
                self._add(outcome, testid, content)

class SingleResult(object):
    __slots__ = "outcome", "testid", "longrepr"
    def __init__(self, outcome, testid, longrepr):
        self.outcome = outcome
        self.testid = testid
        self.longrepr = longrepr
