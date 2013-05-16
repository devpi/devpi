
import json

from devpi_server.urlutil import DistURL

import logging

log = logging.getLogger(__name__)

class DB:
    HCONFIG = "ixconfig:{stage}"
    HFILES = "files:{stage}"

    def __init__(self, xom):
        self.xom = xom
        self.redis = xom.redis
        # XXX set some defaults
        if not self.getbases("~hpk42/dev"):
            self.setbases("~hpk42/dev", "ext/pypi")

    def getstagename(self, user, index):
        return "%s/%s" % (user, index)

    def getbases(self, stagename):
        bases = self.redis.hget(self.HCONFIG.format(stage=stagename),  "bases")
        if bases:
            return tuple(bases.split(","))
        return ()

    def setbases(self, stagename, bases):
        self.redis.hset(self.HCONFIG.format(stage=stagename), "bases", bases)

    def op_with_bases(self, opname, stagename, **kw):
        op = getattr(self, opname)
        op_perstage = getattr(self, opname + "_perstage")
        entries = op_perstage(stagename, **kw)
        for base in self.getbases(stagename):
            base_entries = op(base, **kw)
            if isinstance(base_entries, int):
                if base_entries == 404:
                    continue
                elif base_entries >= 500 or base_entries < 0 :
                    return base_entries
            entries.extend(base_entries)
        return entries

    def getreleaselinks(self, stagename, projectname):
        return self.op_with_bases("getreleaselinks", stagename,
                            projectname=projectname)

    def getreleaselinks_perstage(self, stagename, projectname):
        if stagename == "ext/pypi":
            return self.xom.extdb.getreleaselinks(projectname)
        key = self.HFILES.format(stage=stagename)
        val = self.redis.hget(key, projectname)
        if not val:
            return []
        files = json.loads(val)
        entries = []
        for relpath in files.values():
            entries.append(self.xom.releasefilestore.getentry(relpath))
        log.debug("%s %s: serving %d entries",
                  stagename, projectname, len(entries))
        return entries

    def getprojectnames(self, stagename):
        return self.op_with_bases("getprojectnames", stagename)

    def getprojectnames_perstage(self, stagename):
        if stagename == "ext/pypi":
            return self.xom.extdb.getprojectnames()
        return []

    def store_releasefile(self, stagename, filename, content):
        assert stagename != "ext/pypi"
        name, version = DistURL(filename).pkgname_and_version
        key = self.HFILES.format(stage=stagename)
        val = self.redis.hget(key, name)
        if val:
            files = json.loads(val)
        else:
            files = {}
        assert filename not in files, (filename, files)
        entry = self.xom.releasefilestore.store(stagename, filename, content)
        files[filename] = entry.relpath
        self.redis.hset(key, name, json.dumps(files))
        log.info("%s: stored releasefile %s", stagename, entry.relpath)
        return entry
