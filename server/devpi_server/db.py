
import os
import py
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
        with self.keyfs.USER(user=user).update() as userconfig:
            return self._setpassword(userconfig, user, password)

    def user_create(self, user, password, email):
        with self.keyfs.USER(user=user).update() as userconfig:
            hash = self._setpassword(userconfig, user, password)
            userconfig["email"] = email
            log.info("created user %r with email %r" %(user, email))
            return hash

    def _setpassword(self, userconfig, user, password):
        userconfig["pwsalt"] = salt = os.urandom(16).encode("base_64")
        userconfig["pwhash"] = hash = getpwhash(password, salt)
        log.info("setting password for user %r", user)
        return hash

    def user_delete(self, user):
        self.keyfs.USER(user=user).delete()

    def user_exists(self, user):
        return self.keyfs.USER(user=user).exists()

    def user_list(self):
        return self.keyfs.USER.listnames("user")

    def user_validate(self, user, password):
        userconfig = self.keyfs.USER(user=user).get(None)
        if userconfig is None:
            return False
        salt = userconfig["pwsalt"]
        pwhash = userconfig["pwhash"]
        if getpwhash(password, salt) == pwhash:
            return pwhash
        return None

    def user_get(self, user):
        d = self.keyfs.USER(user=user).get()
        del d["pwsalt"]
        del d["pwhash"]
        return d

    def user_indexconfig_get(self, user, index):
        userconfig = self.keyfs.USER(user=user).get()
        try:
            return userconfig["indexes"][index]
        except KeyError:
            return None

    def user_indexconfig_set(self, user, index=None, **kw):
        if index is None:
            user, index = user.split("/")
        assert kw["type"] in ("stage", "mirror")
        with self.keyfs.USER(user=user).locked_update() as userconfig:
            indexes = userconfig.setdefault("indexes", {})
            ixconfig = indexes.setdefault(index, {})
            ixconfig.update(kw)
            if not set(ixconfig) == _ixconfigattr:
                raise ValueError("incomplete config: %s" % ixconfig)
            log.debug("configure_index %s/%s: %s", user, index, ixconfig)
            return ixconfig

    def user_indexconfig_delete(self, user, index):
        with self.keyfs.USER(user=user).locked_update() as userconfig:
            indexes = userconfig.get("indexes") or {}
            if index not in indexes:
                log.info("index %s/%s not exists", user, index)
                return False
            del indexes[index]
            log.info("deleted index %s/%s" %(user, index))
            return True

    # stage handling

    def getstage(self, user, index=None):
        if index is None:
            user, index = user.split("/")
        ixconfig = self.user_indexconfig_get(user, index)
        if not ixconfig:
            return None
        if ixconfig["type"] == "stage":
            return PrivateStage(self, user, index, ixconfig)
        elif ixconfig["type"] == "mirror":
            return self.xom.extdb
        else:
            raise ValueError("unknown index type %r" % ixconfig["type"])

    def getstagename(self, user, index):
        return "%s/%s" % (user, index)

    def getindexconfig(self, stagename):
        user, index = stagename.split("/")
        return self.user_indexconfig_get(user, index)

    def create_stage(self, user, index=None,
                     type="stage", bases=("/ext/pypi",),
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
            log.debug("%s %s: %d entries", base, kw, len(base_entries))
            entries.extend(base_entries)
        return entries

    def getreleaselinks(self, projectname):
        return self.op_with_bases("getreleaselinks", projectname=projectname)

    def getreleaselinks_perstage(self, projectname):
        key = self.keyfs.STAGELINKS(user=self.user, index=self.index,
                                     name=projectname)
        files = key.get()
        entries = []
        for relpath in files.values():
            entries.append(self.xom.releasefilestore.getentry(relpath))
        return entries

    def getprojectnames(self):
        return self.op_with_bases("getprojectnames")

    def getprojectnames_perstage(self):
        return sorted(self.keyfs.STAGELINKS.listnames("name",
                            user=self.user, index=self.index))

    def store_releasefile(self, filename, content):
        name, version = DistURL(filename).pkgname_and_version
        key = self.keyfs.STAGELINKS(user=self.user, index=self.index,
                                     name=name)
        with key.locked_update() as files:
            if not self.ixconfig.get("volatile") and filename in files:
                return 409
            entry = self.xom.releasefilestore.store(self.user, self.index,
                                                    filename, content)
            files[filename] = entry.relpath
            log.info("%s: stored releasefile %s", self.name, entry.relpath)
            return entry

    def store_doczip(self, name, content):
        assert content
        key = self.keyfs.STAGEDOCS(user=self.user, index=self.index, name=name)

        # XXX collission checking
        #
        unzipfile = py.std.zipfile.ZipFile(py.io.BytesIO(content))

        # XXX locking?
        tempdir = self.keyfs.mkdtemp(name)
        members = unzipfile.namelist()
        for name in members:
            fpath = tempdir.join(name, abs=True)
            if not fpath.relto(tempdir):
                raise ValueError("invalid path name:" + name)
            if name.endswith(os.sep):
                fpath.ensure(dir=1)
            else:
                fpath.dirpath().ensure(dir=1)
                with fpath.open("wb") as f:
                    f.write(unzipfile.read(name))
        keypath = key.filepath
        if keypath.check():
            old = keypath.new(basename="old-" + keypath.basename)
            keypath.move(old)
            tempdir.move(keypath)
            old.remove()
        else:
            keypath.dirpath().ensure(dir=1)
            tempdir.move(keypath)
        return keypath
