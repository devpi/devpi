from __future__ import unicode_literals
import posixpath
import py
import json
from devpi_common.metadata import (sorted_sameproject_links,
                                   get_latest_version)
from devpi_common.validation import validate_metadata, normalize_name
from devpi_common.types import ensure_unicode, cached_property
from .auth import crypt_password, verify_password
from .filestore import FileEntry, split_md5
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
    "type volatile bases uploadtrigger_jenkins acl_upload custom_data".split())

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

class BaseStage:
    def get_project_version(self, name, version):
        return ProjectVersion(self, name, version)

    def get_link_from_entrypath(self, entrypath):
        entry = self.xom.filestore.get_file_entry(entrypath)
        pv = self.get_project_version(entry.projectname, entry.version)
        links = pv.get_links(entrypath=entrypath)
        assert len(links) < 2
        return links[0] if links else None

    def store_toxresult(self, link, toxresultdata):
        assert isinstance(toxresultdata, dict), toxresultdata
        return link.pv.new_reflink(
                rel="toxresult",
                file_content=json.dumps(toxresultdata).encode("utf-8"),
                for_entrypath=link)

    def get_toxresults(self, link):
        l = []
        for reflink in link.pv.get_links(rel="toxresult", for_entrypath=link):
            data = reflink.entry.file_get_content().decode("utf-8")
            l.append(json.loads(data))
        return l

    def get_projectconfig(self, name):
        assert py.builtin._istext(name)
        all_projectconfig = {}
        for stage, res in self.op_sro("get_projectconfig_perstage", name=name):
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

    def getreleaselinks(self, projectname):
        all_links = []
        basenames = set()
        stagename2res = {}
        for stage, res in self.op_sro("getreleaselinks_perstage",
                                      projectname=projectname):
            stagename2res[stage.name] = res
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
        for stagename, res in stagename2res.items():
            if res != 404:
                break
        else:
            return res  # no stage has the project
        return sorted_sameproject_links(all_links)

    def get_project_info(self, name):
        kwdict = {"name": name}
        for stage, res in self.op_sro("get_project_info_perstage", **kwdict):
            if res is not None:
                return res

    def getprojectnames(self):
        all_names = set()
        for stage, names in self.op_sro("getprojectnames_perstage"):
            if isinstance(names, int):
                return names
            all_names.update(names)
        return sorted(all_names)

    def op_sro(self, opname, **kw):
        results = []
        for stage in self._sro():
            stage_result = getattr(stage, opname)(**kw)
            results.append((stage, stage_result))
        return results

    def _sro(self):
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


class PrivateStage(BaseStage):
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


    # registering project and version metadata
    #
    #class MetadataExists(Exception):
    #    """ metadata exists on a given non-volatile index. """

    class RegisterNameConflict(Exception):
        """ a conflict while trying to register metadata. """

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

    def project_delete(self, name):
        for version in self.get_projectconfig_perstage(name):
            self.project_version_delete(name, version, cleanup=False)
        with self.key_projectnames.update() as projectnames:
            projectnames.remove(name)
        threadlog.info("deleting project %s", name)
        self.key_projconfig(name).delete()

    def project_version_delete(self, name, version, cleanup=True):
        pv = self.get_project_version(name, version)
        if version not in pv.projectconfig:
            return False
        pv.remove_links()
        del pv.projectconfig[version]
        if cleanup and not pv.projectconfig:
            self.project_delete(name)
        return True

    def project_exists(self, name):
        return self.key_projconfig(name).exists()

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

    #
    # getting release links
    #

    def getreleaselinks_perstage(self, projectname):
        projectconfig = self.get_projectconfig_perstage(projectname)
        if isinstance(projectconfig, int):
            return projectconfig
        files = []
        for version in projectconfig:
            pv = self.get_project_version(projectname, version)
            for link in pv.get_links("releasefile"):
                files.append(link.entry)
        return files

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
        pv = self.get_project_version(name, version)
        entry = pv.create_linked_entry(
                rel="releasefile",
                basename=filename,
                file_content=content,
                entry_extra=dict(last_modified=last_modified),
        )
        return entry

    def store_doczip(self, name, version, content):
        if not version:
            version = self.get_metadata_latest_perstage(name)["version"]
            threadlog.info("store_doczip: derived version of %s is %s",
                           name, version)
        basename = "%s-%s.doc.zip" % (name, version)
        pv = self.get_project_version(name, version)
        entry = pv.create_linked_entry(
                rel="doczip",
                basename=basename,
                file_content=content,
        )
        return entry

    def get_doczip(self, name, version):
        """ get documentation zip as an open file
        (or None if no docs exists). """
        pv = self.get_project_version(name, version)
        links = pv.get_links(rel="doczip")
        if links:
            assert len(links) == 1, links
            return links[0].entry.file_get_content()



class ELink:
    """ model Link using entrypathes for referencing. """
    def __init__(self, pv, linkdict):
        self.linkdict = linkdict
        self.pv = pv
        self.basename = posixpath.basename(self.entrypath)

    def __getattr__(self, name):
        try:
            return self.linkdict[name]
        except KeyError:
            if name == "for_entrypath":
                return None
            raise AttributeError(name)

    def __repr__(self):
        return "<ELink rel=%r entrypath=%r>" %(self.rel, self.entrypath)

    @cached_property
    def entry(self):
        return self.pv.filestore.get_file_entry(self.entrypath)


class ProjectVersion:
    def __init__(self, stage, projectname, version, projectconfig=None):
        self.stage = stage
        self.filestore = stage.xom.filestore
        self.projectname = projectname
        self.version = version
        if projectconfig is None:
            self.key_projectconfig = self.stage.key_projconfig(name=projectname)
            self.projectconfig = self.key_projectconfig.get()
        else:
            self.projectconfig = projectconfig
        self.verdata = self.projectconfig.setdefault(version, {})
        if not self.verdata:
            self.verdata["name"] = projectname
            self.verdata["version"] = version
            self._mark_dirty()

    def create_linked_entry(self, rel, basename, file_content,
            entry_extra=None):
        assert isinstance(file_content, bytes)
        entry_extra = entry_extra or {}
        for link in self.get_links(rel=rel, basename=basename):
            if not self.stage.ixconfig.get("volatile"):
                return 409
            self.remove_links(rel=rel, basename=basename)
        file_entry = self._create_file_entry(basename, file_content)
        for k,v in entry_extra.items():
            setattr(file_entry, k, v)
        self._add_link_to_file_entry(rel, file_entry)
        return file_entry

    def new_reflink(self, rel, file_content, for_entrypath):
        if isinstance(for_entrypath, ELink):
            for_entrypath = for_entrypath.entrypath
        links = self.get_links(entrypath=for_entrypath)
        assert len(links) == 1, "need exactly one reference, got %s" %(links,)
        base_entry = links[0].entry
        other_reflinks = self.get_links(rel=rel, for_entrypath=for_entrypath)
        filename = "%s.%s%d" %(base_entry.basename, rel, len(other_reflinks))
        entry = self._create_file_entry(filename, file_content,
                                        ref_md5=base_entry.md5)
        return self._add_link_to_file_entry(rel, entry, for_entrypath=for_entrypath)

    def remove_links(self, rel=None, basename=None, for_entrypath=None):
        linkdicts = self._get_inplace_linkdicts()
        del_links = self.get_links(rel=rel, basename=basename, for_entrypath=for_entrypath)
        was_deleted = []
        for link in del_links:
            link.entry.delete()
            linkdicts.remove(link.linkdict)
            was_deleted.append(link.entrypath)
            threadlog.info("deleted %r link %s", link.rel, link.entrypath)
        if linkdicts:
            for entrypath in was_deleted:
                self.remove_links(for_entrypath=entrypath)
        if was_deleted:
            self._mark_dirty()

    def get_links(self, rel=None, basename=None, entrypath=None, for_entrypath=None):
        if isinstance(for_entrypath, ELink):
            for_entrypath = for_entrypath.entrypath
        def fil(link):
            return (not rel or rel==link.rel) and \
                   (not basename or basename==link.basename) and \
                   (not entrypath or entrypath==link.entrypath) and \
                   (not for_entrypath or for_entrypath==link.for_entrypath)
        return list(filter(fil, [ELink(self, linkdict)
                           for linkdict in self.verdata.get("+elinks", [])]))

    def _create_file_entry(self, basename, file_content, ref_md5=None):
        if ref_md5 is None:
            md5dir = None
        else:
            md5dir = "/".join(split_md5(ref_md5))
        entry = self.filestore.store(
                    user=self.stage.user.name, index=self.stage.index,
                    basename=basename,
                    file_content=file_content,
                    md5dir=md5dir)
        entry.projectname = self.projectname
        entry.version = self.version
        return entry

    def _mark_dirty(self):
        self.key_projectconfig.set(self.projectconfig)
        threadlog.debug("marking dirty %s", self.key_projectconfig)

    def _get_inplace_linkdicts(self):
        return self.verdata.setdefault("+elinks", [])

    def _add_link_to_file_entry(self, rel, file_entry, for_entrypath=None):
        if isinstance(for_entrypath, ELink):
            for_entrypath = for_entrypath.entrypath
        relextra = {}
        if for_entrypath:
            relextra["for_entrypath"] = for_entrypath
        linkdicts = self._get_inplace_linkdicts()
        new_linkdict = dict(rel=rel, entrypath=file_entry.relpath,
                            md5=file_entry.md5, **relextra)
        linkdicts.append(new_linkdict)
        threadlog.info("added %r link %s", rel, file_entry.relpath)
        self._mark_dirty()
        return ELink(self, new_linkdict)


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

    # type "stage" related
    keyfs.add_key("PROJCONFIG", "{user}/{index}/{name}/.config", dict)
    keyfs.add_key("PROJNAMES", "{user}/{index}/.projectnames", set)
    keyfs.add_key("STAGEFILE",
                  "{user}/{index}/+f/{md5a}/{md5b}/{filename}", dict)

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

