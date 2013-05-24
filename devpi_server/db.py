
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

_ixconfigattr = set("type volatile bases".split())

class DB:

    def __init__(self, xom):
        self.xom = xom
        self.keyfs = xom.keyfs

    # user handling
    def user_setpassword(self, user, password):
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

    def user_indexconfig_get(self, user, index):
        userconfig = self.keyfs.USER(name=user).get()
        try:
            return userconfig["indexes"][index]
        except KeyError:
            return None

    def user_indexconfig_set(self, user, index=None, **kw):
        if index is None:
            user, index = user.split("/")
        with self.keyfs.USER(name=user).locked_update() as userconfig:
            indexes = userconfig.setdefault("indexes", {})
            ixconfig = indexes.setdefault(index, {})
            ixconfig.update(kw)
            if not set(ixconfig) == _ixconfigattr:
                raise ValueError("incomplete config: %s" % ixconfig)
            log.debug("configure_index %s/%s: %s", user, index, ixconfig)

    # stage handling

    def getstage(self, user, index=None):
        if index is None:
            user, index = user.split("/")
        ixconfig = self.user_indexconfig_get(user, index)
        if not ixconfig:
            return None
        if ixconfig["type"] == "private":
            return PrivateStage(self, user, index, ixconfig)
        elif ixconfig["type"] == "pypimirror":
            return self.xom.extdb

    def getstagename(self, user, index):
        return "%s/%s" % (user, index)

    def getindexconfig(self, stagename):
        user, index = stagename.split("/")
        return self.user_indexconfig_get(user, index)

    def create_stage(self, user, index=None,
                     type="private", bases=("/ext/pypi",),
                     volatile=True):
        self.user_indexconfig_set(user, index, type=type, bases=bases,
                                  volatile=volatile)
        return self.getstage(user, index)


class PrivateStage:
    def __init__(self, db, user, index, ixconfig):
        self.db = db
        self.xom = db.xom
        self.keyfs = db.keyfs
        self.user = user
        self.index = index
        self.name = user + "/" + index
        self.ixconfig = ixconfig

    def configure(self, **kw):
        assert _ixconfigattr.issuperset(kw)
        config = self.ixconfig
        config.update(kw)
        self.db.user_indexconfig_set(self.user, self.index, **config)

    def op_with_bases(self, opname, **kw):
        op_perstage = getattr(self, opname + "_perstage")
        entries = op_perstage(**kw)
        for base in self.ixconfig["bases"]:
            stage = self.db.getstage(base)
            base_entries = getattr(stage, opname)(**kw)
            if isinstance(base_entries, int):
                if base_entries == 404:
                    continue
                elif base_entries >= 500 or base_entries < 0 :
                    return base_entries
            entries.extend(base_entries)
        return entries

    def getreleaselinks(self, projectname):
        return self.op_with_bases("getreleaselinks", projectname=projectname)

    def getreleaselinks_perstage(self, projectname):
        key = self.keyfs.HSTAGEFILES(stage=self.name, name=projectname)
        files = key.get()
        entries = []
        for relpath in files.values():
            entries.append(self.xom.releasefilestore.getentry(relpath))
        log.debug("%s %s: serving %d entries",
                  self.name, projectname, len(entries))
        return entries

    def getprojectnames(self):
        return self.op_with_bases("getprojectnames")

    def getprojectnames_perstage(self):
        return sorted(self.keyfs.HSTAGEFILES.listnames("name", stage=self.name))

    def store_releasefile(self, filename, content):
        name, version = DistURL(filename).pkgname_and_version
        key = self.keyfs.HSTAGEFILES(stage=self.name, name=name)
        with key.locked_update() as files:
            if not self.ixconfig.get("volatile") and filename in files:
                return 409
            entry = self.xom.releasefilestore.store(self.name,
                                                    filename, content)
            files[filename] = entry.relpath
            log.info("%s: stored releasefile %s", self.name, entry.relpath)
            return entry


