
import logging

log = logging.getLogger(__name__)

class DB:
    HCONFIGPREFIX = "ixconfig:"

    def __init__(self, xom):
        self.xom = xom
        self.redis = xom.redis
        # XXX set some defaults
        if not self.getbases("~hpk42/dev"):
            self.setbases("~hpk42/dev", "ext/pypi")

    def getstagename(self, user, index):
        return "%s/%s" % (user, index)

    def getbases(self, stagename):
        bases = self.redis.hget(self.HCONFIGPREFIX + stagename,  "bases")
        if bases:
            return tuple(bases.split(","))
        return ()

    def setbases(self, stagename, bases):
        self.redis.hset(self.HCONFIGPREFIX + stagename, "bases", bases)

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
        return []

    def getprojectnames(self, stagename):
        return self.op_with_bases("getprojectnames", stagename)

    def getprojectnames_perstage(self, stagename):
        if stagename == "ext/pypi":
            return self.xom.extdb.getprojectnames()
        return []
