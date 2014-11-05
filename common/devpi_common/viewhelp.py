import posixpath
from .url import URL


class ViewLinkStore:
    def __init__(self, url, versiondata):
        self.url = URL(url)
        self.versiondata = versiondata

    def get_links(self, rel=None, for_href=None, basename=None):
        l = []
        for linkdict in self.versiondata.get("+links", []):
            viewlink = ViewLink(self.url, linkdict)
            if (not rel or viewlink.rel == rel) and \
               (not for_href or viewlink.for_href==for_href) and \
               (not basename or viewlink.basename == basename):
                l.append(viewlink)
        return l

    def get_link(self, rel=None, basename=None, for_href=None):
        links = self.get_links(rel=rel, basename=basename, for_href=for_href)
        assert len(links) == 1
        return links[0]

    def shadowed(self):
        l = []
        for verdata in self.versiondata.get("+shadowing", []):
            l.append(ViewLinkStore(self.url.url, verdata))
        return l


class ViewLink:
    def __init__(self, base_url, linkdict):
        self.__dict__.update(linkdict)
        self.href = base_url.joinpath(self.href).url
        self.basename = posixpath.basename(self.href)

    def __repr__(self):
        return "<%s rel=%r href=%r>" % (
            self.__class__.__name__, self.rel, self.href)


class ToxResultEnv:
    def __init__(self, result, envname):
        self.host = result["host"]
        self.platform = result["platform"]
        self.envname = envname
        self.key = (self.host, self.platform, self.envname)
        env = result["testenvs"][envname]
        try:
            self.pyversion = env["python"]["version"].split(None, 1)[0]
        except KeyError:
            self.pyversion = None
        self.get = env.get
        self.setup = self._get_commands_info(self.get("setup", []))
        self.test = self._get_commands_info(self.get("test", []))
        self.failed = self.setup["failed"] or self.test["failed"]

    def _get_commands_info(self, commands):
        result = dict(
            failed=any(x["retcode"] != "0" for x in commands),
            commands=[])
        for command in commands:
            result["commands"].append(dict(
                failed=command["retcode"] != "0",
                command=" ".join(command.get("command", [])),
                output=command.get("output", [])))
        return result


def get_toxenvs(toxresult, seen, newest=True):
    envs = []
    for envname in sorted(toxresult["testenvs"]):
        toxenv = ToxResultEnv(toxresult, envname)
        if toxenv.key in seen:
            continue
        if newest:
            seen.add(toxenv.key)
        envs.append(toxenv)
    return envs


def iter_toxresults(links, load, newest=True):
    seen = set()
    for link in reversed(links):
        try:
            toxresult = load(link)
        except IOError:
            yield link, None
            continue
        try:
            yield link, get_toxenvs(toxresult, seen, newest=newest)
        except KeyError:
            yield link, None
