
import os
import re
import py
from .urlutil import DistURL
from .vendor._description_utils import processDescription
from .urlutil import sorted_by_version, get_latest_version
from .auth import crypt_password, verify_password
from .validation import validate_metadata, normalize_name

import logging

log = logging.getLogger(__name__)

def run_passwd(db, user):
    if not db.user_exists(user):
        log.error("user %r not found" % user)
        return 1
    for i in range(3):
        pwd = py.std.getpass.getpass("enter password for %s: " % user)
        pwd2 = py.std.getpass.getpass("repeat password for %s: " % user)
        if pwd != pwd2:
            log.error("password don't match")
        else:
            break
    else:
        log.error("no password set")
        return 1
    db.user_modify(user, password=pwd)


_ixconfigattr = set(
    "type volatile bases uploadtrigger_jenkins acl_upload".split())

class DB:
    class InvalidIndexconfig(Exception):
        def __init__(self, messages):
            self.messages = messages
            Exception.__init__(self, messages)

    def __init__(self, xom):
        self.xom = xom
        self.keyfs = xom.keyfs

    def is_empty(self):
        userlist = self.user_list()
        if len(userlist) != 1 or "root" not in userlist:
            return False
        userconfig = self.user_get("root")
        rootindexes = list(userconfig.get("indexes", []))
        return rootindexes == ["pypi"]

    def user_create(self, user, password, email=None):
        with self.keyfs.USER(user=user).update() as userconfig:
            self._setpassword(userconfig, user, password)
            if email:
                userconfig["email"] = email
            log.info("created user %r with email %r" %(user, email))

    def _user_set(self, user, newuserconfig):
        with self.keyfs.USER(user=user).update() as userconfig:
            if "indexes" not in newuserconfig:
                newuserconfig["indexes"] = userconfig.get("indexes", {})
            userconfig.clear()
            userconfig.update(newuserconfig)
            log.info("internal: set user information %r", user)

    def user_modify(self, user, password=None, email=None):
        with self.keyfs.USER(user=user).update() as userconfig:
            modified = []
            if password is not None:
                self._setpassword(userconfig, user, password)
                modified.append("password=*******")
            if email:
                userconfig["email"] = email
                modified.append("email=%s" % email)
            log.info("modified user %r: %s" %(user, ", ".join(modified)))

    def _setpassword(self, userconfig, user, password):
        salt, hash = crypt_password(password)
        userconfig["pwsalt"] = salt
        userconfig["pwhash"] = hash
        log.info("setting password for user %r", user)

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
        if verify_password(password, pwhash, salt):
            return pwhash
        return None

    def user_get(self, user, credentials=False):
        d = self.keyfs.USER(user=user).get()
        if not d:
            return d
        if not credentials:
            del d["pwsalt"]
            del d["pwhash"]
        d["username"] = user
        return d

    def _get_user_and_index(self, user, index=None):
        if index is None:
            user = user.strip("/")
            user, index = user.split("/")
        return user, index

    def index_get(self, user, index=None):
        user, index = self._get_user_and_index(user, index)
        userconfig = self.keyfs.USER(user=user).get()
        try:
            indexconfig = userconfig["indexes"][index]
        except KeyError:
            return None
        if "acl_upload" not in indexconfig:
            indexconfig["acl_upload"] = [user]
        return indexconfig

    def _normalize_bases(self, bases):
        # check and normalize base indices
        messages = []
        newbases = []
        for base in bases:
            try:
                base_user, base_index = self._get_user_and_index(base)
            except ValueError:
                messages.append("invalid base index spec: %r" % (base,))
            else:
                if self.index_get(base) is None:
                    messages.append("base index %r does not exist" %(base,))
                else:
                    newbases.append("%s/%s" % (base_user, base_index))
        if messages:
            raise self.InvalidIndexconfig(messages)
        return newbases

    def index_get(self, user, index=None):
        user, index = self._get_user_and_index(user, index)
        userconfig = self.keyfs.USER(user=user).get()
        return userconfig.get("indexes", {}).get(index)

    def index_exists(self, user, index=None):
        return bool(self.index_get(user, index))

    def index_create(self, user, index=None, type="stage",
                     volatile=True, bases=("root/pypi",),
                     uploadtrigger_jenkins=None,
                     acl_upload=None):
        user, index = self._get_user_and_index(user, index)

        if acl_upload is None:
            acl_upload = [user]
        bases = tuple(self._normalize_bases(bases))

        # modify user/indexconfig
        with self.keyfs.USER(user=user).locked_update() as userconfig:
            indexes = userconfig.setdefault("indexes", {})
            assert index not in indexes, indexes[index]
            indexes[index] = ixconfig = dict(
                type=type, volatile=volatile, bases=bases,
                uploadtrigger_jenkins=uploadtrigger_jenkins,
                acl_upload=acl_upload)
            log.info("created index %s/%s: %s", user, index, ixconfig)
            return ixconfig

    def index_modify(self, user, index=None, **kw):
        user, index = self._get_user_and_index(user, index)
        diff = list(set(kw).difference(_ixconfigattr))
        if diff:
            raise self.InvalidIndexconfig(
                ["invalid keys for index configuration: %s" %(diff,)])
        if "bases" in kw:
            kw["bases"] = tuple(self._normalize_bases(kw["bases"]))

        # modify user/indexconfig
        with self.keyfs.USER(user=user).locked_update() as userconfig:
            ixconfig = userconfig["indexes"][index]
            ixconfig.update(kw)
            log.info("modified index %s/%s: %s", user, index, ixconfig)
            return ixconfig

    def index_delete(self, user, index=None):
        user, index = self._get_user_and_index(user, index)
        with self.keyfs.USER(user=user).locked_update() as userconfig:
            indexes = userconfig.get("indexes", {})
            if index not in indexes:
                log.info("index %s/%s not exists", user, index)
                return False
            del indexes[index]
            self._remove_indexdir(user, index)
            log.info("deleted index config %s/%s" %(user, index))
            return True

    def _remove_indexdir(self, user, index):
        p = self.keyfs.INDEXDIR(user=user, index=index).filepath
        if p.check():
            p.remove()
            log.info("deleted index %s/%s" %(user, index))
            return True

    # stage handling

    def getstage(self, user, index=None):
        user, index = self._get_user_and_index(user, index)
        ixconfig = self.index_get(user, index)
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

    def create_stage(self, user, index=None, **kw):
        self.index_create(user, index, **kw)
        return self.getstage(user, index)

class ProjectInfo:
    def __init__(self, stage, name):
        self.name = name
        self.stage = stage


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

    def can_upload(self, username):
        return username in self.ixconfig.get("acl_upload", [])

    def _reconfigure(self, **kw):
        self.ixconfig = self.db.index_modify(self.name, **kw)

    def _get_sro(self):
        """ return stage resolution order. """
        todo = [self]
        seen = set()
        while todo:
            stage = todo.pop(0)
            yield stage
            seen.add(stage.name)
            for base in stage.ixconfig["bases"]:
                if base not in seen:
                    todo.append(self.db.getstage(base))

    def op_with_bases(self, opname, **kw):
        opname += "_perstage"
        results = []
        for stage in self._get_sro():
            stage_result = getattr(stage, opname)(**kw)
            results.append((stage, stage_result))
        return results

    def log_info(self, *args):
        log.info("%s: %s" % (self.name, args[0]), *args[1:])
    #
    # registering project and version metadata
    #
    #class MetadataExists(Exception):
    #    """ metadata exists on a given non-volatile index. """

    class RegisterNameConflict(Exception):
        """ a conflict while trying to register metadata. """

    def get_project_info(self, name):
        """ return first matching project info object for the given name
        or None if no project exists. """
        for stage, res in self.op_with_bases("get_project_info", name=name):
            if res is not None:
                return res

    def get_project_info_perstage(self, name):
        """ return normalized name for the given name or None
        if no project exists. """
        names = self.getprojectnames_perstage()
        norm2name = dict([(normalize_name(x), x) for x in names])
        realname = norm2name.get(normalize_name(name), None)
        if realname:
            return ProjectInfo(self, realname)

    def register_metadata(self, metadata):
        """ register metadata.  Raises ValueError in case of metadata
        errors. """
        validate_metadata(metadata)
        name = metadata["name"]
        version = metadata["version"]
        # check if the project exists already under its normalized
        info = self.get_project_info(name)
        if info:
            log.info("got project info with name %r" % info.name)
        else:
            log.debug("project %r does not exist, good", name)
        if info is not None and info.name != name:
            raise self.RegisterNameConflict(info)
        self._register_metadata(metadata)

    def _register_metadata(self, metadata):
        name = metadata["name"]
        version = metadata["version"]
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        with key.locked_update() as projectconfig:
            #if not self.ixconfig["volatile"] and projectconfig:
            #    raise self.MetadataExists(
            #        "%s-%s exists on non-volatile %s" %(
            #        name, version, self.name))
            versionconfig = projectconfig.setdefault(version, {})
            versionconfig.update(metadata)
            self.log_info("store_metadata %s-%s", name, version)
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

    def project_delete(self, name):
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        key.delete()

    def project_version_delete(self, name, version):
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        with key.locked_update() as projectconfig:
            if version not in projectconfig:
                return False
            self.log_info("deleting version %r of project %r", version, name)
            del projectconfig[version]
        # XXX race condition if concurrent addition happens
        if not projectconfig:
            self.log_info("no version left, deleting project %r", name)
            key.delete()
        return True

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
        # on win32 we need to make sure that we only return
        # something if we know about the exact name, not a
        # case-different one
        info = self.get_project_info(name)
        if info and info.name == name:
            projectconfig = self.get_projectconfig(name)
            return projectconfig.get(version)

    def get_metadata_latest(self, name):
        versions = self.get_projectconfig(name)
        maxver = get_latest_version(versions)
        return self.get_metadata(name, maxver.string)

    def get_projectconfig_perstage(self, name):
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        return key.get()

    def get_projectconfig(self, name):
        all_projectconfig = {}
        for stage, res in self.op_with_bases("get_projectconfig", name=name):
            if isinstance(res, int):
                if res == 404:
                    continue
                return res
            for ver in res:
                if ver not in all_projectconfig:
                    all_projectconfig[ver] = res[ver]
                else:
                    l = all_projectconfig[ver].setdefault("+shadowing", [])
                    l.append(res[ver])
        return all_projectconfig

    #
    # getting release links
    #

    def getreleaselinks(self, projectname):
        all_links = []
        basenames = set()
        for stage, res in self.op_with_bases("getreleaselinks",
                                          projectname=projectname):
            if isinstance(res, int):
                if res == 404:
                    continue
                return res
            for entry in res:
                if entry.eggfragment:
                    key = entry.eggfragment
                else:
                    key = entry.basename
                if key not in basenames:
                    basenames.add(key)
                    all_links.append(entry)
        all_links = sorted_by_version(all_links, attr="basename")
        all_links.reverse()
        return all_links

    def getreleaselinks_perstage(self, projectname):
        projectconfig = self.get_projectconfig_perstage(projectname)
        if isinstance(projectconfig, int):
            return projectconfig
        files = []
        for verdata in projectconfig.values():
            files.extend(
                map(self.xom.filestore.getentry,
                    verdata.get("+files", {}).values()))
        return files

    def getprojectnames(self):
        all_names = set()
        for stage, names in self.op_with_bases("getprojectnames"):
            if isinstance(names, int):
                return names
            all_names.update(names)
        return sorted(all_names)


    def getprojectnames_perstage(self):
        names = self.keyfs.PROJCONFIG.listnames("name",
                        user=self.user, index=self.index)
        # on case insensitive filesystems we can't be sure
        # we have case-sensitive names so we do a slow
        # iteration over all projectconfig files
        realnames = set()
        for name in names:
            projectconfig = self.get_projectconfig_perstage(name)
            for metadata in projectconfig.values():
                realnames.add(metadata.get("name", name))
        return list(realnames)


    class MissesRegistration(Exception):
        """ store_releasefile requires pre-existing release metadata. """

    def store_releasefile(self, filename, content, last_modified=None):
        name, version = DistURL(filename).pkgname_and_version
        info = self.get_project_info(name)
        name = getattr(info, "name", name)
        if not self.get_metadata(name, version):
            raise self.MissesRegistration(name, version)
        log.debug("project name of %r is %r", filename, name)
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        with key.locked_update() as projectconfig:
            verdata = projectconfig.setdefault(version, {})
            files = verdata.setdefault("+files", {})
            if not self.ixconfig.get("volatile") and filename in files:
                return 409
            entry = self.xom.filestore.store(self.user, self.index,
                                filename, content, last_modified=last_modified)
            files[filename] = entry.relpath
            self.log_info("store_releasefile %s", entry.relpath)
            return entry

    def store_doczip(self, name, content):
        """ unzip doc content for the specified "name" project. """
        assert content
        key = self._doc_key(name)

        # XXX locking (unzipping could happen concurrently in theory)
        tempdir = self.keyfs.mkdtemp(name)
        unzip_to_dir(content, tempdir)
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

    def get_doczip(self, name):
        """ get zip file content of the current docs or None. """
        key = self._doc_key(name)
        basedir = key.filepath
        if not basedir.check():
            return
        content = create_zipfile(basedir)
        return content

    def _doc_key(self, name):
        return self.keyfs.STAGEDOCS(user=self.user, index=self.index,
                                    name=name)


def create_zipfile(basedir):
    f = py.io.BytesIO()
    zip = py.std.zipfile.ZipFile(f, "w")
    _writezip(zip, basedir)
    zip.close()
    return f.getvalue()

def _writezip(zip, basedir):
    for p in basedir.visit():
        if p.check(dir=1):
            if not p.listdir():
                path = p.relto(basedir) + "/"
                zipinfo = py.std.zipfile.ZipInfo(path)
                zip.writestr(zipinfo, "")
        else:
            path = p.relto(basedir)
            zip.writestr(path, p.read("rb"))

def unzip_to_dir(content, basedir):
    unzipfile = py.std.zipfile.ZipFile(py.io.BytesIO(content))
    members = unzipfile.namelist()
    for name in members:
        fpath = basedir.join(name, abs=True)
        if not fpath.relto(basedir):
            raise ValueError("invalid path name:" + name)
        if name.endswith(os.sep) or name[-1] == "/":
            fpath.ensure(dir=1)
        else:
            fpath.dirpath().ensure(dir=1)
            with fpath.open("wb") as f:
                f.write(unzipfile.read(name))

