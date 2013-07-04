
import os
import py
from .urlutil import DistURL
from .vendor._description_utils import processDescription
import hashlib
from .urlutil import sorted_by_version

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
        if d:
            del d["pwsalt"]
            del d["pwhash"]
            d["username"] = user
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

            log.info("deleted index config %s/%s" %(user, index))
            return True

    def delete_index(self, user, index):
        p = self.keyfs.INDEXDIR(user=user, index=index).filepath
        if p.check():
            p.remove()
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
                     type="stage", bases=("/root/pypi",),
                     volatile=True):
        self.user_indexconfig_set(user, index, type=type, bases=bases,
                                  volatile=volatile)
        return self.getstage(user, index)


class PrivateStage:
    metadata_keys = """
        name version summary home_page author author_email
        license description keywords platform classifiers download_url
    """.split()

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

    #
    # registering project and version metadata
    #
    def register_metadata(self, metadata):
        name = metadata["name"]
        version = metadata["version"]
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        with key.locked_update() as projectconfig:
            versionconfig = projectconfig.setdefault(version, {})
            versionconfig.update(metadata)
        desc = metadata.get("description")
        if desc:
            html = processDescription(desc)
            key = self.keyfs.RELDESCRIPTION(
                user=self.user, index=self.index, name=name, version=version)
            if py.builtin._istext(html):
                html = html.encode("utf8")
            key.set(html)

    def project_add(self, name):
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        with key.locked_update() as projectconfig:
            pass

    def project_exists(self, name):
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        return key.exists()

    def get_description(self, name, version):
        key = self.keyfs.RELDESCRIPTION(user=self.user, index=self.index,
            name=name, version=version)
        return key.get()

    def get_description_versions(self, name):
        return self.keyfs.RELDESCRIPTION.listnames("version",
            user=self.user, index=self.index, name=name)

    def get_metadata(self, name, version):
        projectconfig = self.get_projectconfig(name)
        return projectconfig.get(version)

    def get_projectconfig(self, name):
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        return key.get()

    #
    # getting release links
    #

    def getreleaselinks(self, projectname):
        l = self.op_with_bases("getreleaselinks", projectname=projectname)
        if isinstance(l, int):
            return l
        l = sorted_by_version(l, attr="basename")
        l.reverse()
        return l

    def getreleaselinks_perstage(self, projectname):
        projectconfig = self.get_projectconfig(projectname)
        files = []
        for verdata in projectconfig.values():
            files.extend(
                map(self.xom.releasefilestore.getentry,
                    verdata.get("+files", {}).values()))
        return files

    def getprojectnames(self):
        return sorted(set(self.op_with_bases("getprojectnames")))

    def getprojectnames_perstage(self):
        return sorted(self.keyfs.PROJCONFIG.listnames("name",
                      user=self.user, index=self.index))

    def store_releasefile(self, filename, content):
        name, version = DistURL(filename).pkgname_and_version
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        with key.locked_update() as projectconfig:
            verdata = projectconfig.setdefault(version, {})
            files = verdata.setdefault("+files", {})
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
