from __future__ import unicode_literals
import posixpath
import sys
import py
import re
import json
from devpi_common.metadata import sorted_sameproject_links, get_latest_version
from devpi_common.validation import validate_metadata, normalize_name
from devpi_common.types import ensure_unicode, cached_property, parse_hash_spec
from time import gmtime
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


_ixconfigattr = set((
    "type", "volatile", "bases", "uploadtrigger_jenkins", "acl_upload",
    "pypi_whitelist", "custom_data"))


class ModelException(Exception):
    """ Base Exception. """
    def __init__(self, msg, *args):
        if args:
            msg = msg % args
        self.msg = msg
        Exception.__init__(self, msg)


class InvalidUser(ModelException):
    """ If a username is invalid or already in use. """


class NotFound(ModelException):
    """ If a project or version cannot be found. """


class UpstreamError(ModelException):
    """ If an upstream could not be reached or didn't respond correctly. """


class MissesRegistration(ModelException):
    """ A prior registration or release metadata is required. """


class NonVolatile(ModelException):
    """ A release is overwritten on a non volatile index. """
    link = None  # the conflicting link


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
    group_regexp = re.compile('^:.*:$')
    name_regexp = re.compile('^[a-zA-Z0-9._-]+$')

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
            raise InvalidUser("username already exists")
        if not cls.name_regexp.match(username):
            threadlog.error("username '%s' will be invalid with next release, use characters, numbers, underscore, dash and dots only" % username)
        if cls.group_regexp.match(username):
            raise InvalidUser("username '%s' is invalid, use characters, numbers, underscore, dash and dots only" % username)
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
        # delete all projects on the index
        for name in self.get().get("indexes", {}):
            self.getstage(name).delete()
        # delete the user information itself
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
                     acl_upload=None, pypi_whitelist=(),
                     custom_data=None):
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
                "acl_upload": acl_upload, "pypi_whitelist": pypi_whitelist,
            }
            if custom_data is not None:
                indexes[index]["custom_data"] = custom_data
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


class BaseStage:
    InvalidUser = InvalidUser
    NotFound = NotFound
    UpstreamError = UpstreamError
    MissesRegistration = MissesRegistration
    NonVolatile = NonVolatile

    def get_linkstore_perstage(self, name, version):
        return LinkStore(self, name, version)

    def get_link_from_entrypath(self, entrypath):
        entry = self.xom.filestore.get_file_entry(entrypath)
        if entry.projectname is None:
            return None
        linkstore = self.get_linkstore_perstage(entry.projectname,
                                                entry.version)
        links = linkstore.get_links(entrypath=entrypath)
        assert len(links) < 2
        return links[0] if links else None

    def store_toxresult(self, link, toxresultdata):
        assert isinstance(toxresultdata, dict), toxresultdata
        linkstore = self.get_linkstore_perstage(link.projectname, link.version)
        return linkstore.new_reflink(
                rel="toxresult",
                file_content=json.dumps(toxresultdata).encode("utf-8"),
                for_entrypath=link)

    def get_toxresults(self, link):
        l = []
        linkstore = self.get_linkstore_perstage(link.projectname, link.version)
        for reflink in linkstore.get_links(rel="toxresult", for_entrypath=link):
            data = reflink.entry.file_get_content().decode("utf-8")
            l.append(json.loads(data))
        return l

    def list_versions(self, projectname):
        assert py.builtin._istext(projectname), "projectname %r not text" % projectname
        versions = set()
        for stage, res in self.op_sro_check_pypi_whitelist(
                "list_versions_perstage", projectname=projectname):
            versions.update(res)
        return versions

    def get_latest_version(self, name, stable=False):
        return get_latest_version(self.list_versions(name), stable=stable)

    def get_latest_version_perstage(self, name, stable=False):
        return get_latest_version(self.list_versions_perstage(name), stable=stable)

    def get_versiondata(self, projectname, version):
        assert py.builtin._istext(projectname), "projectname %r not text" % projectname
        result = {}
        for stage, res in self.op_sro_check_pypi_whitelist(
                "get_versiondata_perstage",
                projectname=projectname, version=version):
            if res:
                if not result:
                    result.update(res)
                else:
                    l = result.setdefault("+shadowing", [])
                    l.append(res)
        return result

    def get_releaselinks(self, projectname):
        all_links = []
        basenames = set()
        stagename2res = {}
        for stage, res in self.op_sro_check_pypi_whitelist(
            "get_releaselinks_perstage", projectname=projectname):
            stagename2res[stage.name] = res
            for link in res:
                if link.eggfragment:
                    key = link.eggfragment
                else:
                    key = link.basename
                if key not in basenames:
                    basenames.add(key)
                    all_links.append(link)
        return sorted_sameproject_links(all_links)

    def get_projectname(self, name):
        for stage, res in self.op_sro("get_projectname_perstage", name=name):
            if res is not None:
                assert py.builtin._istext(res), (repr(res), stage.name)
                return res

    def has_pypi_base(self, name):
        name = ensure_unicode(name)
        private_hit = whitelisted = False
        for stage in self._sro():
            if stage.ixconfig["type"] == "mirror":
                return stage.get_projectname_perstage(name) and \
                       (not private_hit or whitelisted)
            private_hit = private_hit or bool(self.get_projectname_perstage(name))
            whitelist = set(stage.ixconfig["pypi_whitelist"])
            whitelisted = whitelisted or '*' in whitelist or name in whitelist

    def op_sro(self, opname, **kw):
        for stage in self._sro():
            yield stage, getattr(stage, opname)(**kw)

    def op_sro_check_pypi_whitelist(self, opname, **kw):
        projectname = kw["projectname"]
        whitelisted = private_hit = False
        for stage in self._sro():
            if stage.ixconfig["type"] == "mirror":
                if private_hit:
                    if not whitelisted:
                        threadlog.debug("%s: private package %r not whitelisted, "
                                        "ignoring root/pypi", opname, projectname)
                        continue
                    threadlog.debug("private package %r whitelisted at stage %s",
                                    projectname, whitelisted.name)
            else:
                whitelist = set(stage.ixconfig["pypi_whitelist"])
                if '*' in whitelist or projectname in whitelist:
                    whitelisted = stage
            res = getattr(stage, opname)(**kw)
            private_hit = private_hit or res
            yield stage, res

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
        self.username = self.user.name
        self.index = index
        self.name = user + "/" + index
        self.ixconfig = ixconfig
        self.key_projectnames = self.keyfs.PROJNAMES(
                    user=self.user.name, index=self.index)

    def modify(self, index=None, **kw):
        diff = list(set(kw).difference(_ixconfigattr))
        if diff:
            raise InvalidIndexconfig(
                ["invalid keys for index configuration: %s" %(diff,)])
        if "bases" in kw:
            kw["bases"] = tuple(normalize_bases(self.xom.model, kw["bases"]))
        if 'acl_upload' in kw:
            for index, name in enumerate(kw['acl_upload']):
                if name.upper() == ':ANONYMOUS:':
                    kw['acl_upload'][index] = name.upper()
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
        for name in self.list_projectnames_perstage().copy():
            self.del_project(name)
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

    def get_projectname_perstage(self, name):
        """ return existing projectname for the given name which may
        be in a non-canonical form. """
        assert py.builtin._istext(name), "name %r not text" % name
        names = self.list_projectnames_perstage()
        if name in names:
            return name
        normname = normalize_name(name)
        for projectname in names:
            if normalize_name(projectname) == normname:
                return projectname

    def set_versiondata(self, metadata):
        """ register metadata.  Raises ValueError in case of metadata
        errors. """
        validate_metadata(metadata)
        name = metadata["name"]
        # check if the project exists already under its normalized
        projectname = self.get_projectname(name)
        log = thread_current_log()
        if projectname is not None and projectname != name:
            log.warn("using already registered name %r for submitted %r "
                     "in stage %r" %(
                      projectname, name, self.name))
            metadata["name"] = projectname
        self._set_versiondata(metadata)

    def key_projversions(self, name):
        name = normalize_name(name)
        return self.keyfs.PROJVERSIONS(
            user=self.user.name, index=self.index, name=name)

    def key_projversion(self, name, version):
        name = normalize_name(name)
        return self.keyfs.PROJVERSION(
            user=self.user.name, index=self.index, name=name, version=version)

    def _set_versiondata(self, metadata):
        name = metadata["name"]
        version = metadata["version"]
        key_projversion = self.key_projversion(name, version)
        versiondata = key_projversion.get()
        if not key_projversion.is_dirty():
            # check if something really changed to prevent
            # unneccessary changes on db/replica level
            for key, val in metadata.items():
                if val != versiondata.get(key):
                    break
            else:
                threadlog.info("not re-registering same metadata for %s-%s",
                               name, version)
                return
        versiondata.update(metadata)
        key_projversion.set(versiondata)
        threadlog.info("set_metadata %s-%s", name, version)
        versions = self.key_projversions(name).get()
        if version not in versions:
            versions.add(version)
            self.key_projversions(name).set(versions)
        projectnames = self.key_projectnames.get()
        if name not in projectnames:
            projectnames.add(name)
            self.key_projectnames.set(projectnames)

    def del_project(self, name):
        for version in self.key_projversions(name).get():
            self.del_versiondata(name, version, cleanup=False)
        with self.key_projectnames.update() as projectnames:
            projectnames.remove(name)
        threadlog.info("deleting project %s", name)
        self.key_projversions(name).delete()

    def del_versiondata(self, name, version, cleanup=True):
        projectname = self.get_projectname_perstage(name)
        if projectname is None:
            raise self.NotFound("project %r not found on stage %r" %
                                (name, self.name))
        versions = self.key_projversions(projectname).get()
        if version not in versions:
            raise self.NotFound("version %r of project %r not found on stage %r" %
                                (version, projectname, self.name))
        linkstore = self.get_linkstore_perstage(projectname, version)
        linkstore.remove_links()
        versions.remove(version)
        self.key_projversion(projectname, version).delete()
        self.key_projversions(projectname).set(versions)
        if cleanup and not versions:
            self.del_project(projectname)

    def list_versions_perstage(self, projectname):
        return self.key_projversions(projectname).get()

    def get_versiondata_perstage(self, projectname, version):
        return self.key_projversion(projectname, version).get()

    def get_releaselinks_perstage(self, projectname):
        links = []
        for version in self.list_versions_perstage(projectname):
            linkstore = self.get_linkstore_perstage(projectname, version)
            links.extend(linkstore.get_links("releasefile"))
        return links

    def list_projectnames_perstage(self):
        return self.key_projectnames.get()

    def store_releasefile(self, name, version, filename, content,
                          last_modified=None):
        filename = ensure_unicode(filename)
        if not self.get_versiondata(name, version):
            # There's a chance the version was guessed from the
            # filename, which might have swapped dashes to underscores
            if '_' in version:
                version = version.replace('_', '-')
                if not self.get_versiondata(name, version):
                    raise MissesRegistration("%s-%s", name, version)
            else:
                raise MissesRegistration("%s-%s", name, version)
        threadlog.debug("project name of %r is %r", filename, name)
        linkstore = self.get_linkstore_perstage(name, version)
        link = linkstore.create_linked_entry(
                rel="releasefile",
                basename=filename,
                file_content=content,
                last_modified=last_modified)
        return link

    def store_doczip(self, name, version, content):
        if not version:
            version = self.get_latest_version_perstage(name)
            threadlog.info("store_doczip: derived version of %s is %s",
                           name, version)
        basename = "%s-%s.doc.zip" % (name, version)
        linkstore = self.get_linkstore_perstage(name, version)
        link = linkstore.create_linked_entry(
                rel="doczip",
                basename=basename,
                file_content=content,
        )
        return link

    def get_doczip(self, name, version):
        """ get documentation zip as an open file
        (or None if no docs exists). """
        linkstore = self.get_linkstore_perstage(name, version)
        links = linkstore.get_links(rel="doczip")
        if links:
            if len(links) > 1:
                def key(link):
                    when = None
                    for log in link.get_logs():
                        when = log.get('when')
                        if when is not None:
                            break
                    return when
                link = max(links, key=key)
                threadlog.warn("Multiple documentation files for %s-%s, returning newest", name, version)
            else:
                link = links[0]
            return link.entry.file_get_content()


class ELink:
    """ model Link using entrypathes for referencing. """
    def __init__(self, filestore, linkdict, projectname, version):
        self.filestore = filestore
        self.linkdict = linkdict
        self.basename = posixpath.basename(self.entrypath)
        self.projectname = projectname
        self.version = version
        if sys.version_info < (3,0):
            for key in linkdict:
                assert py.builtin._istext(key)

    @property
    def hash_spec(self):
        return self.linkdict.get("hash_spec", "")

    @property
    def hash_value(self):
        return self.hash_spec.split("=")[1]

    def matches_checksum(self, content):
        hash_algo, hash_value = parse_hash_spec(self.hash_spec)
        if not hash_algo:
            return True
        return hash_algo(content).hexdigest() == hash_value

    def __getattr__(self, name):
        try:
            return self.linkdict[name]
        except KeyError:
            if name in ("for_entrypath", "eggfragment", "rel"):
                return None
            raise AttributeError(name)

    def __repr__(self):
        return "<ELink rel=%r entrypath=%r>" % (self.rel, self.entrypath)

    @cached_property
    def entry(self):
        return self.filestore.get_file_entry(self.entrypath)

    def add_log(self, what, who, **kw):
        d = {"what": what, "who": who, "when": gmtime()[:6]}
        if sys.version_info < (3,0):
            # make sure keys are unicode as they are on py3
            kw = dict((py.builtin.text(name), value) for name, value in kw.items())
        d.update(kw)
        self._log.append(d)

    def add_logs(self, logs):
        self._log.extend(logs)

    def get_logs(self):
        return list(self._log)


class LinkStore:
    def __init__(self, stage, projectname, version):
        self.stage = stage
        self.filestore = stage.xom.filestore
        self.projectname = projectname
        self.version = version
        self.verdata = stage.get_versiondata_perstage(projectname, version)
        if not self.verdata:
            raise MissesRegistration("%s-%s on stage %s",
                                     projectname, version, stage.name)

    def get_file_entry(self, relpath):
        return self.filestore.get_file_entry(relpath)

    def create_linked_entry(self, rel, basename, file_content, last_modified=None):
        assert isinstance(file_content, bytes)
        overwrite = None
        for link in self.get_links(rel=rel, basename=basename):
            if not self.stage.ixconfig.get("volatile"):
                exc = NonVolatile("rel=%s basename=%s on stage %s" % (
                    rel, basename, self.stage.name))
                exc.link = link
                raise exc
            assert overwrite is None
            overwrite = sum(x.get('count', 0)
                            for x in link.get_logs() if x.get('what') == 'overwrite')
            self.remove_links(rel=rel, basename=basename)
        file_entry = self._create_file_entry(basename, file_content)
        if last_modified is not None:
            file_entry.last_modified = last_modified
        link = self._add_link_to_file_entry(rel, file_entry)
        if overwrite is not None:
            link.add_log('overwrite', None, count=overwrite + 1)
        return link

    def new_reflink(self, rel, file_content, for_entrypath):
        if isinstance(for_entrypath, ELink):
            for_entrypath = for_entrypath.entrypath
        links = self.get_links(entrypath=for_entrypath)
        assert len(links) == 1, "need exactly one reference, got %s" %(links,)
        base_entry = links[0].entry
        other_reflinks = self.get_links(rel=rel, for_entrypath=for_entrypath)
        filename = "%s.%s%d" %(base_entry.basename, rel, len(other_reflinks))
        entry = self._create_file_entry(filename, file_content,
                                        ref_hash_spec=base_entry.hash_spec)
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

    def get_links(self, rel=None, basename=None, entrypath=None,
                  for_entrypath=None):
        if isinstance(for_entrypath, ELink):
            for_entrypath = for_entrypath.entrypath
        def fil(link):
            return (not rel or rel==link.rel) and \
                   (not basename or basename==link.basename) and \
                   (not entrypath or entrypath==link.entrypath) and \
                   (not for_entrypath or for_entrypath==link.for_entrypath)
        return list(filter(fil, [ELink(self.filestore, linkdict, self.projectname, self.version)
                           for linkdict in self.verdata.get("+elinks", [])]))

    def _create_file_entry(self, basename, file_content, ref_hash_spec=None):
        entry = self.filestore.store(
                    user=self.stage.user.name, index=self.stage.index,
                    basename=basename,
                    file_content=file_content,
                    dir_hash_spec=ref_hash_spec)
        entry.projectname = self.projectname
        entry.version = self.version
        return entry

    def _mark_dirty(self):
        self.stage._set_versiondata(self.verdata)

    def _get_inplace_linkdicts(self):
        return self.verdata.setdefault("+elinks", [])

    def _add_link_to_file_entry(self, rel, file_entry, for_entrypath=None):
        if isinstance(for_entrypath, ELink):
            for_entrypath = for_entrypath.entrypath
        new_linkdict = {"rel": rel, "entrypath": file_entry.relpath,
                        "hash_spec": file_entry.hash_spec, "_log": []}
        if for_entrypath:
            new_linkdict["for_entrypath"] = for_entrypath
        linkdicts = self._get_inplace_linkdicts()
        linkdicts.append(new_linkdict)
        threadlog.info("added %r link %s", rel, file_entry.relpath)
        self._mark_dirty()
        return ELink(self.filestore, new_linkdict, self.projectname,
                     self.version)


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
    keyfs.add_key("PROJVERSIONS", "{user}/{index}/{name}/.versions", set)
    keyfs.add_key("PROJVERSION", "{user}/{index}/{name}/{version}/.config", dict)
    keyfs.add_key("PROJNAMES", "{user}/{index}/.projectnames", set)
    keyfs.add_key("STAGEFILE",
                  "{user}/{index}/+f/{hashdir_a}/{hashdir_b}/{filename}", dict)

    sub = EventSubscribers(xom)
    keyfs.notifier.on_key_change("PROJVERSION", sub.on_changed_version_config)
    keyfs.notifier.on_key_change("STAGEFILE", sub.on_changed_file_entry)
    keyfs.notifier.on_key_change("PYPI_SERIALS_LOADED", sub.on_init_pypiserials)


class EventSubscribers:
    """ the 'on_' functions are called within in the notifier thread. """
    def __init__(self, xom):
        self.xom = xom

    def on_init_pypiserials(self, ev):
        xom = self.xom
        hook = xom.config.hook
        with xom.keyfs.transaction(write=False, at_serial=ev.at_serial):
            stage = xom.model.getstage("root", "pypi")
            name2serials = stage.pypimirror.name2serials
            hook.devpiserver_pypi_initial(stage, name2serials)

    def on_changed_version_config(self, ev):
        """ when version config is changed for a project in a stage"""
        params = ev.typedkey.params
        user = params["user"]
        index = params["index"]
        keyfs = self.xom.keyfs
        hook = self.xom.config.hook
        # find out if metadata changed
        if ev.back_serial == -1:
            old = {}
        else:
            assert ev.back_serial < ev.at_serial
            try:
                old = keyfs.get_value_at(ev.typedkey, ev.back_serial)
            except KeyError:
                old = {}
        with keyfs.transaction(write=False, at_serial=ev.at_serial):
            # XXX slightly flaky logic for detecting metadata changes
            metadata = ev.value
            source = metadata or old
            projectname, version = source["name"], source["version"]
            if metadata != old:
                stage = self.xom.model.getstage(user, index)
                hook.devpiserver_on_changed_versiondata(
                    stage, projectname, version, metadata)

    def on_changed_file_entry(self, ev):
        """ when a file entry is modified. """
        params = ev.typedkey.params
        user = params.get("user")
        index = params.get("index")
        keyfs = self.xom.keyfs
        with keyfs.transaction(at_serial=ev.at_serial):
            stage = self.xom.model.getstage(user, index)
            if stage is not None and stage.ixconfig["type"] == "mirror":
                return  # we don't trigger on file changes of pypi mirror
            entry = FileEntry(self.xom, ev.typedkey, meta=ev.value)
            if not entry.projectname or not entry.version:
                # the entry was deleted
                return
            projectname = stage.get_projectname(entry.projectname)
            linkstore = stage.get_linkstore_perstage(
                                                projectname, entry.version)
            links = linkstore.get_links(basename=entry.basename)
            if len(links) == 1:
                self.xom.config.hook.devpiserver_on_upload(
                    stage=stage, projectname=projectname,
                    version=entry.version,
                    link=links[0])

