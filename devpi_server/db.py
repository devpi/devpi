
from devpi_server.urlutil import DistURL

import logging

log = logging.getLogger(__name__)

class IndexConfig:
    """ Unserialized index configuration (using Python types). """
    def __init__(self, stagename, type="", bases="", volatile=False):
        self.stagename = stagename
        self.type = type
        self.bases = tuple([x for x in bases.split(",") if x])
        self.volatile = bool(int(volatile))

    def _getmapping(self):
        """ serialize into key/value strings. """
        return dict(type=self.type,
                    volatile=str(int(bool(self.volatile))),
                    bases=",".join(self.bases),
        )

class DB:

    def __init__(self, xom):
        self.xom = xom
        self.keyfs = xom.keyfs

    def getstagename(self, user, index):
        return "%s/%s" % (user, index)

    def getindexconfig(self, stagename):
        keyfs = self.keyfs
        mapping = keyfs.HSTAGECONFIG(stage=stagename).get()
        return IndexConfig(stagename=stagename, **mapping)

    def configure_index(self, stagename, type="private",
                        bases=(), volatile=None):
        ixconfig = self.getindexconfig(stagename)
        if type:
            ixconfig.type = type
        if bases is not None:
            ixconfig.bases =  bases
        if volatile is not None:
            ixconfig.volatile = volatile
        mapping = ixconfig._getmapping()
        log.debug("configure_index %s: %s", stagename, mapping)
        keyfs = self.keyfs
        keyfs.HSTAGECONFIG(stage=stagename).set(mapping)

    def op_with_bases(self, opname, stagename, **kw):
        ixconfig = self.getindexconfig(stagename)
        if not ixconfig.type:
            return 404
        op = getattr(self, opname)
        op_perstage = getattr(self, opname + "_perstage")
        entries = op_perstage(stagename, **kw)
        for base in ixconfig.bases:
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
        key = self.keyfs.HSTAGEFILES(stage=stagename, name=projectname)
        files = key.get()
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
        ixconfig = self.getindexconfig(stagename)
        #if not ixconfig.type:
        #    return 404
        name, version = DistURL(filename).pkgname_and_version
        key = self.keyfs.HSTAGEFILES(stage=stagename, name=name)
        with key.locked_update() as files:
            if not ixconfig.volatile and filename in files:
                return 409
            entry = self.xom.releasefilestore.store(stagename,
                                                    filename, content)
            files[filename] = entry.relpath
            log.info("%s: stored releasefile %s", stagename, entry.relpath)
            return entry


