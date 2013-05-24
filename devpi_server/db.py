
import os
from devpi_server.urlutil import DistURL
import hashlib

import logging

log = logging.getLogger(__name__)

def getpwhash(password, salt):
    hash = hashlib.sha256()
    hash.update(salt)
    hash.update(password)
    return hash.hexdigest()

class DB:

    def __init__(self, xom):
        self.xom = xom
        self.keyfs = xom.keyfs

    # user handling
    def user_create(self, user, password):
        with self.keyfs.USER(name=user).update() as userconfig:
            userconfig["pwsalt"] = salt = os.urandom(16).encode("base_64")
            userconfig["pwhash"] = getpwhash(password, salt)

    def user_delete(self, user):
        self.keyfs.USER(name=user).delete()

    def user_exists(self, user):
        return self.keyfs.USER(name=user).exists()

    def user_list(self):
        return self.keyfs.USER.listnames("name")

    def user_validate(self, user, password):
        userconfig = self.keyfs.USER(name=user).get(None)
        if userconfig is None:
            return False
        salt = userconfig["pwsalt"]
        pwhash = userconfig["pwhash"]
        return getpwhash(password, salt) == pwhash

    # stage handling
    def getstagename(self, user, index):
        return "%s/%s" % (user, index)

    def getindexconfig(self, stagename):
        return self.keyfs.HSTAGECONFIG(stage=stagename).get()

    def configure_index(self, stagename, type="private",
                        bases=(), volatile=None):
        with self.keyfs.HSTAGECONFIG(stage=stagename).update() as ixconfig:
            if type:
                ixconfig["type"] = type
            if bases is not None:
                ixconfig["bases"] = bases
            if volatile is not None:
                ixconfig["volatile"] = volatile
            log.debug("configure_index %s: %s", stagename, ixconfig)

    def op_with_bases(self, opname, stagename, **kw):
        ixconfig = self.getindexconfig(stagename)
        if not ixconfig:
            return 404
        op = getattr(self, opname)
        op_perstage = getattr(self, opname + "_perstage")
        entries = op_perstage(stagename, **kw)
        for base in ixconfig["bases"]:
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
            if not ixconfig.get("volatile") and filename in files:
                return 409
            entry = self.xom.releasefilestore.store(stagename,
                                                    filename, content)
            files[filename] = entry.relpath
            log.info("%s: stored releasefile %s", stagename, entry.relpath)
            return entry


