from __future__ import unicode_literals

import py
from devpi_common.metadata import (sorted_sameproject_links,
                                   get_latest_version)
from devpi_common.validation import validate_metadata, normalize_name
from devpi_common.types import ensure_unicode
from devpi_common.archive import Archive
from .vendor._description_utils import processDescription
from .auth import crypt_password, verify_password

import logging

log = logging.getLogger(__name__)

def run_passwd(xom, user):
    user = xom.get_user(user)
    if not user.exists():
        log.error("user %r not found" % user.name)
        return 1
    for i in range(3):
        pwd = py.std.getpass.getpass("enter password for %s: " % user.name)
        pwd2 = py.std.getpass.getpass("repeat password for %s: " % user.name)
        if pwd != pwd2:
            log.error("password don't match")
        else:
            break
    else:
        log.error("no password set")
        return 1
    user.modify(password=pwd)


_ixconfigattr = set(
    "type volatile bases uploadtrigger_jenkins acl_upload".split())

class UserList:
    def __init__(self, xom, keyfs):
        self.xom = xom
        self.keyfs = keyfs

    def __iter__(self):
        return (User(self, name) 
                    for name in self.keyfs.USER.listnames("user"))

    def __getitem__(self, name):
        return User(self, name)

class User:
    def __init__(self, parent, name):
        self.__parent__ = parent
        self.keyfs = parent.keyfs
        self.xom = parent.xom
        self.name = name

    @property
    def key(self):
        return self.keyfs.USER(user=self.name)

    def create(self, password, email=None):
        with self.key.update() as userconfig:
            self._setpassword(userconfig, password)
            if email:
                userconfig["email"] = email
            if "indexes" not in userconfig:
                userconfig["indexes"] = {}
            log.info("created user %r with email %r" %(self.name, email))


    def _set(self, newuserconfig):
        with self.key.update() as userconfig:
            userconfig.update(newuserconfig)
            log.info("internal: set user information %r", self.name)

    def modify(self, password=None, email=None):
        with self.key.update() as userconfig:
            modified = []
            if password is not None:
                self._setpassword(userconfig, password)
                modified.append("password=*******")
            if email:
                userconfig["email"] = email
                modified.append("email=%s" % email)
            log.info("modified user %r: %s" %(self.name, ", ".join(modified)))

    def _setpassword(self, userconfig, password):
        salt, hash = crypt_password(password)
        userconfig["pwsalt"] = salt
        userconfig["pwhash"] = hash
        log.info("setting password for user %r", self.name)

    def delete(self):
        self.key.delete()

    def exists(self):
        return self.key.exists()

    def validate(self, password):
        userconfig = self.key.get(None)
        if userconfig is None:
            return False
        salt = userconfig["pwsalt"]
        pwhash = userconfig["pwhash"]
        if verify_password(password, pwhash, salt):
            return pwhash
        return None

    def get(self, credentials=False):
        d = self.key.get()
        if not d:
            return d
        if not credentials:
            del d["pwsalt"]
            del d["pwhash"]
        d["username"] = self.name
        return d

    def create_stage(self, index, type="stage",
                     volatile=True, bases=("root/pypi",),
                     uploadtrigger_jenkins=None,
                     acl_upload=None):
        if acl_upload is None:
            acl_upload = [self.name]
        bases = tuple(normalize_bases(self.xom, bases))

        # modify user/indexconfig
        with self.key.locked_update() as userconfig:
            indexes = userconfig.setdefault("indexes", {})
            assert index not in indexes, indexes[index]
            indexes[index] = ixconfig = {
                "type": type, "volatile": volatile, "bases": bases,
                "uploadtrigger_jenkins": uploadtrigger_jenkins,
                "acl_upload": acl_upload
            }
        stage = self.getstage(index)
        log.info("created index %s: %s", stage.name, stage.ixconfig)
        return stage

    def getstage(self, indexname):
        ixconfig = self.get()["indexes"].get(indexname, {})
        if not ixconfig:
            return None
        if ixconfig["type"] == "stage":
            return PrivateStage(self.xom, self.name, indexname, ixconfig)
        elif ixconfig["type"] == "mirror":
            return self.xom.pypistage
        else:
            raise ValueError("unknown index type %r" % ixconfig["type"])
         
 

class InvalidIndexconfig(Exception):
    def __init__(self, messages):
        self.messages = messages
        Exception.__init__(self, messages)


class ProjectInfo:
    def __init__(self, stage, name):
        self.name = name
        self.stage = stage

    def __str__(self):
        return "<ProjectInfo %s stage %s>" %(self.name, self.stage.name)


class PrivateStage:
    metadata_keys = """
        name version summary home_page author author_email
        license description keywords platform classifiers download_url
    """.split()
    # taken from distlib.metadata (6th October)
    metadata_list_fields = ('platform', 'classifier', 'classifiers',
               'obsoletes',
               'requires', 'provides', 'obsoletes-Dist',
               'provides-dist', 'requires-dist', 'requires-external',
               'project-url', 'supported-platform', 'setup-requires-Dist',
               'provides-extra', 'extension')

    def __init__(self, xom, user, index, ixconfig):
        self.xom = xom
        self.keyfs = xom.keyfs
        self.user = user
        self.index = index
        self.name = user + "/" + index
        self.ixconfig = ixconfig

    def exists(self):
        return True

    def can_upload(self, username):
        return username in self.ixconfig.get("acl_upload", [])

    def _reconfigure(self, **kw):
        self.ixconfig = self.modify(**kw)

    def modify(self, index=None, **kw):
        user = self.xom.get_user(self.user)
        diff = list(set(kw).difference(_ixconfigattr))
        if diff:
            raise InvalidIndexconfig(
                ["invalid keys for index configuration: %s" %(diff,)])
        if "bases" in kw:
            kw["bases"] = tuple(normalize_bases(self.xom, kw["bases"]))

        # modify user/indexconfig
        with user.key.locked_update() as userconfig:
            ixconfig = userconfig["indexes"][self.index]
            ixconfig.update(kw)
            log.info("modified index %s: %s", self.name, ixconfig)
            return ixconfig

    def get(self):
        userconfig = self.xom.get_user(self.user).key.get()
        return userconfig.get("indexes", {}).get(self.index)

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
                    todo.append(self.xom.getstage(base))

    def delete(self):
        user = self.xom.get_user(self.user)
        with user.key.locked_update() as userconfig:
            indexes = userconfig.get("indexes", {})
            if self.index not in indexes:
                log.info("index %s not exists" % self.index)
                return False
            del indexes[self.index]
            self._remove_indexdir()
            log.info("deleted index config %s" % self.name)
            return True

    def _remove_indexdir(self):
        p = self.keyfs.INDEXDIR(user=self.user, index=self.index).filepath
        if p.check():
            p.remove()
            log.info("deleted index %s" % self.name)
            return True

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
        kwdict = {"name": name}
        for stage, res in self.op_with_bases("get_project_info", **kwdict):
            if res is not None:
                return res

    def get_project_info_perstage(self, name):
        """ return normalized name for the given name or None
        if no project exists. """
        assert py.builtin._istext(name)
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
        # check if the project exists already under its normalized
        info = self.get_project_info(name)
        if info:
            log.info("got project info with name %r" % info.name)
        else:
            log.debug("project %r does not exist, good", name)
        if info is not None and info.name != name:
            log.error("project %r has other name %r in stage %s" %(
                      name, info.name, self.name))
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
        return py.builtin._totext(key.get(), "utf-8")

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

    def get_metadata_latest_perstage(self, name):
        versions = self.get_projectconfig_perstage(name)
        maxver = get_latest_version(versions)
        return self.get_metadata(name, maxver.string)

    def get_projectconfig_perstage(self, name):
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        return key.get()

    def get_projectconfig(self, name):
        assert py.builtin._istext(name)
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
        return sorted_sameproject_links(all_links)

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

    def store_releasefile(self, name, version, filename, content,
                          last_modified=None):
        filename = ensure_unicode(filename)
        if not self.get_metadata(name, version):
            raise self.MissesRegistration(name, version)
        log.debug("project name of %r is %r", filename, name)
        key = self.keyfs.PROJCONFIG(user=self.user,
                                    index=self.index, name=name)
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

    def store_doczip(self, name, version, docfile):
        """ store zip file and unzip doc content for the
        specified "name" project. """
        if not version:
            version = self.get_metadata_latest_perstage(name)["version"]
            log.info("store_doczip: derived version of %s is %s",
                     name, version)
        key = self.keyfs.PROJCONFIG(user=self.user, index=self.index, name=name)
        with key.locked_update() as projectconfig:
            verdata = projectconfig[version]
            filename = "%s-%s.doc.zip" % (name, version)
            entry = self.xom.filestore.store_file(self.user, self.index,
                                filename, docfile)
            verdata["+doczip"] = entry.relpath
        # unpack
        key = self._doc_key(name, version)

        # XXX locking? (unzipping could happen concurrently in theory)
        tempdir = self.keyfs.mkdtemp(name)
        with Archive(entry.filepath.open("rb")) as archive:
            archive.extract(tempdir)
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

    def get_doczip(self, name, version):
        """ get documentation zip as an open file
        (or None if no docs exists). """
        metadata = self.get_metadata(name, version)
        if metadata:
            doczip = metadata.get("+doczip")
            if doczip:
                entry = self.xom.filestore.getentry(doczip)
                if entry:
                    return entry.filepath.open("rb")

    def _doc_key(self, name, version):
        assert version
        return self.keyfs.STAGEDOCS(user=self.user, index=self.index,
                                    name=name, version=version)

def normalize_bases(xom, bases):
    # check and normalize base indices
    messages = []
    newbases = []
    for base in bases:
        try:
            stage_base = xom.getstage(base)
        except ValueError:
            messages.append("invalid base index spec: %r" % (base,))
        else:
            if stage_base is None:
                messages.append("base index %r does not exist" %(base,))
            else:
                newbases.append(stage_base.name)
    if messages:
        raise InvalidIndexconfig(messages)
    return newbases


