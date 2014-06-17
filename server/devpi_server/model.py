from __future__ import unicode_literals

import py
from devpi_common.metadata import (sorted_sameproject_links,
                                   get_latest_version)
from devpi_common.validation import validate_metadata, normalize_name
from devpi_common.types import ensure_unicode
from .vendor._description_utils import processDescription
from .auth import crypt_password, verify_password
from .filestore import FileEntry
from .log import threadlog, thread_current_log


def run_passwd(root, username):
    user = root.get_user(username)
    log = thread_current_log()
    if user is None:
        log.error("user %r not found" % username)
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

class RootModel:
    def __init__(self, xom):
        self.xom = xom
        self.keyfs = xom.keyfs

    def create_user(self, username, password, email=None):
        return User.create(self, username, password, email)

    def get_user(self, name):
        user = User(self, name)
        if user.key.exists():
            return user

    def get_userlist(self):
        return [User(self, name) for name in self.keyfs.USERLIST.get()]

    def get_usernames(self):
        return set(user.name for user in self.get_userlist())

    def _get_user_and_index(self, user, index=None):
        if not py.builtin._istext(user):
            user = user.decode("utf8")
        if index is None:
            user = user.strip("/")
            user, index = user.split("/")
        else:
            if not py.builtin._istext(index):
                index = index.decode("utf8")
        return user, index

    def getstage(self, user, index=None):
        username, index = self._get_user_and_index(user, index)
        user = self.get_user(username)
        if user is not None:
            return user.getstage(index)

    def is_empty(self):
        userlist = list(self.get_userlist())
        if len(userlist) == 1:
            user, = userlist
            if user.name == "root":
                rootindexes = user.get().get("indexes", [])
                return list(rootindexes) == ["pypi"]
        return False


class User:
    def __init__(self, parent, name):
        self.__parent__ = parent
        self.keyfs = parent.keyfs
        self.xom = parent.xom
        self.name = name

    @property
    def key(self):
        return self.keyfs.USER(user=self.name)

    @classmethod
    def create(cls, model, username, password, email):
        userlist = model.keyfs.USERLIST.get()
        if username in userlist:
            raise ValueError("username already exists")
        user = cls(model, username)
        with user.key.update() as userconfig:
            user._setpassword(userconfig, password)
            if email:
                userconfig["email"] = email
            userconfig.setdefault("indexes", {})
        userlist.add(username)
        model.keyfs.USERLIST.set(userlist)
        threadlog.info("created user %r with email %r" %(username, email))
        return user

    def _set(self, newuserconfig):
        with self.key.update() as userconfig:
            userconfig.update(newuserconfig)
            threadlog.info("internal: set user information %r", self.name)

    def modify(self, password=None, email=None):
        with self.key.update() as userconfig:
            modified = []
            if password is not None:
                self._setpassword(userconfig, password)
                modified.append("password=*******")
            if email:
                userconfig["email"] = email
                modified.append("email=%s" % email)
            threadlog.info("modified user %r: %s", self.name,
                           ", ".join(modified))

    def _setpassword(self, userconfig, password):
        salt, hash = crypt_password(password)
        userconfig["pwsalt"] = salt
        userconfig["pwhash"] = hash
        threadlog.info("setting password for user %r", self.name)

    def delete(self):
        self.key.delete()
        with self.keyfs.USERLIST.update() as userlist:
            userlist.remove(self.name)

    def validate(self, password):
        userconfig = self.key.get()
        if not userconfig:
            return False
        salt = userconfig["pwsalt"]
        pwhash = userconfig["pwhash"]
        if verify_password(password, pwhash, salt):
            return pwhash
        return None

    def get(self, credentials=False):
        d = self.key.get().copy()
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
        bases = tuple(normalize_bases(self.xom.model, bases))

        # modify user/indexconfig
        with self.key.update() as userconfig:
            indexes = userconfig.setdefault("indexes", {})
            assert index not in indexes, indexes[index]
            indexes[index] = {
                "type": type, "volatile": volatile, "bases": bases,
                "uploadtrigger_jenkins": uploadtrigger_jenkins,
                "acl_upload": acl_upload
            }
        stage = self.getstage(index)
        threadlog.info("created index %s: %s", stage.name, stage.ixconfig)
        return stage

    def getstage(self, indexname):
        ixconfig = self.get()["indexes"].get(indexname, {})
        if not ixconfig:
            return None
        if ixconfig["type"] == "stage":
            return PrivateStage(self.xom, self.name, indexname, ixconfig)
        elif ixconfig["type"] == "mirror":
            from .extpypi import PyPIStage
            return PyPIStage(self.xom)
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
        self.model = xom.model
        self.keyfs = xom.keyfs
        self.user = self.model.get_user(user)
        self.index = index
        self.name = user + "/" + index
        self.ixconfig = ixconfig
        self.key_projectnames = self.keyfs.PROJNAMES(
                    user=self.user.name, index=self.index)

    def can_upload(self, username):
        return username in self.ixconfig.get("acl_upload", [])

    def modify(self, index=None, **kw):
        diff = list(set(kw).difference(_ixconfigattr))
        if diff:
            raise InvalidIndexconfig(
                ["invalid keys for index configuration: %s" %(diff,)])
        if "bases" in kw:
            kw["bases"] = tuple(normalize_bases(self.xom.model, kw["bases"]))

        # modify user/indexconfig
        with self.user.key.update() as userconfig:
            ixconfig = userconfig["indexes"][self.index]
            ixconfig.update(kw)
            threadlog.info("modified index %s: %s", self.name, ixconfig)
            self.ixconfig = ixconfig
            return ixconfig

    def get(self):
        userconfig = self.user.get()
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
                    todo.append(self.model.getstage(base))

    def delete(self):
        # delete all projects on this index
        for name in list(self.getprojectnames_perstage()):
            self.project_delete(name)
        with self.user.key.update() as userconfig:
            indexes = userconfig.get("indexes", {})
            if self.index not in indexes:
                threadlog.info("index %s not exists" % self.index)
                return False
            del indexes[self.index]

    def op_with_bases(self, opname, **kw):
        opname += "_perstage"
        results = []
        for stage in self._get_sro():
            stage_result = getattr(stage, opname)(**kw)
            results.append((stage, stage_result))
        return results

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
        log = thread_current_log()
        if info:
            log.info("got project info with name %r" % info.name)
        else:
            log.debug("project %r does not exist, good", name)
        if info is not None and info.name != name:
            log.error("project %r has other name %r in stage %s" %(
                      name, info.name, self.name))
            raise self.RegisterNameConflict(info)
        self._register_metadata(metadata)

    def key_projconfig(self, name):
        return self.keyfs.PROJCONFIG(user=self.user.name,
                                     index=self.index, name=name)

    def _register_metadata(self, metadata):
        name = metadata["name"]
        version = metadata["version"]
        with self.key_projconfig(name).update() as projectconfig:
            #if not self.ixconfig["volatile"] and projectconfig:
            #    raise self.MetadataExists(
            #        "%s-%s exists on non-volatile %s" %(
            #        name, version, self.name))
            versionconfig = projectconfig.setdefault(version, {})
            versionconfig.update(metadata)
            threadlog.info("store_metadata %s-%s", name, version)
        projectnames = self.key_projectnames.get()
        if name not in projectnames:
            projectnames.add(name)
            self.key_projectnames.set(projectnames)
        desc = metadata.get("description")
        if desc:
            html = processDescription(desc)
            doc_key = self.keyfs.RELDESCRIPTION(user=self.user.name,
                        index=self.index, name=name, version=version)
            if py.builtin._istext(html):
                html = html.encode("utf8")
            doc_key.set(html)

    def project_delete(self, name):
        for version in self.get_projectconfig_perstage(name):
            self.project_version_delete(name, version, cleanup=False)
        with self.key_projectnames.update() as projectnames:
            projectnames.remove(name)
        self.key_projconfig(name).delete()

    def project_version_delete(self, name, version, cleanup=True):
        with self.key_projconfig(name).update() as projectconfig:
            verdata = projectconfig.pop(version, None)
            if verdata is None:
                return False
            threadlog.info("deleting version %r of project %r", version, name)
            for relpath in verdata.get("+files", {}).values():
                entry = self.xom.filestore.get_file_entry(relpath)
                entry.delete()
        if cleanup and not projectconfig:
            threadlog.info("no version left, deleting project %r", name)
            self.project_delete(name)
        return True

    def project_exists(self, name):
        return self.key_projconfig(name).exists()

    def get_description(self, name, version):
        key = self.keyfs.RELDESCRIPTION(user=self.user.name,
            index=self.index, name=name, version=version)
        return py.builtin._totext(key.get(), "utf-8")

    def get_description_versions(self, name):
        versions = []
        projectconfig = self.key_projconfig(name).get()
        for ver in projectconfig:
            key_reldesc = self.keyfs.RELDESCRIPTION(version=ver,
                user=self.user.name, index=self.index, name=name)
            if key_reldesc.exists():
                versions.append(ver)
        return versions

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
        return self.key_projconfig(name).get()

    def get_projectconfig(self, name):
        assert py.builtin._istext(name)
        all_projectconfig = {}
        for stage, res in self.op_with_bases("get_projectconfig", name=name):
            if isinstance(res, int):
                if res == 404:
                    continue
                assert 0, res
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
                map(self.xom.filestore.get_file_entry,
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
        return self.key_projectnames.get()

    class MissesRegistration(Exception):
        """ store_releasefile requires pre-existing release metadata. """

    def store_releasefile(self, name, version, filename, content,
                          last_modified=None):
        filename = ensure_unicode(filename)
        if not self.get_metadata(name, version):
            raise self.MissesRegistration(name, version)
        threadlog.debug("project name of %r is %r", filename, name)
        key = self.key_projconfig(name=name)
        with key.update() as projectconfig:
            verdata = projectconfig.setdefault(version, {})
            files = verdata.setdefault("+files", {})
            if filename in files:
                if not self.ixconfig.get("volatile"):
                    return 409
                entry = self.xom.filestore.get_file_entry(files[filename])
                entry.delete()
            entry = self.xom.filestore.store(self.user.name, self.index,
                                filename, content, last_modified=last_modified)
            entry.projectname = name
            entry.version = version
            files[filename] = entry.relpath
            threadlog.info("store_releasefile %s", entry.relpath)
            return entry

    def store_doczip(self, name, version, content):
        """ store zip file and unzip doc content for the
        specified "name" project. """
        assert isinstance(content, bytes)
        if not version:
            version = self.get_metadata_latest_perstage(name)["version"]
            threadlog.info("store_doczip: derived version of %s is %s",
                           name, version)
        key = self.key_projconfig(name=name)
        with key.update() as projectconfig:
            verdata = projectconfig[version]
            filename = "%s-%s.doc.zip" % (name, version)
            entry = self.xom.filestore.store(self.user.name, self.index,
                                filename, content)
            entry.projectname = name
            entry.version = version
            verdata["+doczip"] = entry.relpath

    def get_doczip(self, name, version):
        """ get documentation zip as an open file
        (or None if no docs exists). """
        metadata = self.get_metadata(name, version)
        if metadata:
            doczip = metadata.get("+doczip")
            if doczip:
                entry = self.xom.filestore.get_file_entry(doczip)
                if entry:
                    return entry.file_get_content()


def normalize_bases(model, bases):
    # check and normalize base indices
    messages = []
    newbases = []
    for base in bases:
        try:
            stage_base = model.getstage(base)
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


def add_keys(xom, keyfs):
    # users and index configuration
    keyfs.add_key("USER", "{user}/.config", dict)
    keyfs.add_key("USERLIST", ".config", set)

    # type pypimirror related data
    keyfs.add_key("PYPI_SERIALS_LOADED", "root/pypi/initiallinks", dict)
    keyfs.add_key("PYPILINKS", "root/pypi/+links/{name}", dict)
    keyfs.add_key("PYPIFILE_NOMD5",
                 "{user}/{index}/+e/{dirname}/{basename}", dict)
    keyfs.add_key("PYPISTAGEFILE",
                  "{user}/{index}/+f/{md5a}/{md5b}/{filename}", dict)

    # type "stage" related
    keyfs.add_key("PROJCONFIG", "{user}/{index}/{name}/.config", dict)
    keyfs.add_key("PROJNAMES", "{user}/{index}/.projectnames", set)
    keyfs.add_key("STAGEFILE", "{user}/{index}/+f/{md5}/{filename}", dict)
    keyfs.add_key("RELDESCRIPTION",
                  "{user}/{index}/{name}/{version}/description_html", bytes)

    keyfs.add_key("ATTACHMENT", "+attach/{md5}/{type}/{num}", bytes)
    keyfs.add_key("ATTACHMENTS", "+attach/.att", dict)

    keyfs.notifier.on_key_change("PROJCONFIG", ProjectChanged(xom))
    keyfs.notifier.on_key_change("STAGEFILE", FileUploaded(xom))
    keyfs.notifier.on_key_change("PYPI_SERIALS_LOADED", PyPISerialsLoaded(xom))


class PyPISerialsLoaded:
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, ev):
        threadlog.info("PyPISerialsLoaded %s", ev.typedkey)
        xom = self.xom
        hook = xom.config.hook
        with xom.keyfs.transaction(write=False, at_serial=ev.at_serial):
            stage = xom.model.getstage("root", "pypi")
            name2serials = stage.pypimirror.name2serials
            hook.devpiserver_pypi_initial(stage, name2serials)


class ProjectChanged:
    """ Event executed in notification thread based on a metadata change. """
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, ev):
        threadlog.info("project_config_changed %s", ev.typedkey)
        params = ev.typedkey.params
        user = params["user"]
        index = params["index"]
        keyfs = self.xom.keyfs
        hook = self.xom.config.hook
        # find out which version changed
        if ev.back_serial == -1:
            old = {}
        else:
            assert ev.back_serial < ev.at_serial
            old = keyfs.get_value_at(ev.typedkey, ev.back_serial)
        with keyfs.transaction(write=False, at_serial=ev.at_serial):
            # XXX slightly flaky logic for detecting metadata changes
            projconfig = ev.value
            if projconfig:
                for ver, metadata in projconfig.items():
                    if metadata != old.get(ver):
                        stage = self.xom.model.getstage(user, index)
                        hook.devpiserver_register_metadata(stage, metadata)
                #else:
                #    threadlog.debug("no metadata change on %s, %s", metadata,
                #                    old.get(ver))


class FileUploaded:
    """ Event executed in notification thread when a file is uploaded
    to a stage. """
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, ev):
        threadlog.info("FileUploaded %s", ev.typedkey)
        params = ev.typedkey.params
        user = params.get("user")
        index = params.get("index")
        keyfs = self.xom.keyfs
        with keyfs.transaction(at_serial=ev.at_serial):
            entry = FileEntry(self.xom, ev.typedkey, meta=ev.value)
            stage = self.xom.model.getstage(user, index)
            if entry.basename.endswith(".doc.zip"):
                self.xom.config.hook.devpiserver_docs_uploaded(
                    stage=stage, name=entry.projectname,
                    version=entry.version,
                    entry=entry)
            # XXX we could add register_releasefile event here

