from __future__ import unicode_literals
import getpass
import posixpath
import sys
import py
import re
import json
from devpi_common.metadata import get_latest_version
from devpi_common.metadata import CompareMixin
from devpi_common.metadata import splitbasename, parse_version
from devpi_common.url import URL
from devpi_common.validation import validate_metadata, normalize_name
from devpi_common.types import ensure_unicode, cached_property, parse_hash_spec
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest
from time import gmtime, strftime
from .auth import hash_password, verify_and_update_password_hash
from .config import hookimpl
from .filestore import FileEntry
from .log import threadlog, thread_current_log
from .readonly import get_mutable_deepcopy


def join_requires(links, requires_python):
    # build list of (key, href, require_python) tuples
    result = []
    for link, require_python in zip_longest(links, requires_python, fillvalue=None):
        key, href = link
        result.append((key, href, require_python))
    return result


def apply_filter_iter(items, filter_iter):
    for item in items:
        if next(filter_iter, True):
            yield item


def run_passwd(root, username):
    user = root.get_user(username)
    log = thread_current_log()
    if user is None:
        log.error("user %r not found" % username)
        return 1
    for i in range(3):
        pwd = getpass.getpass("enter password for %s: " % user.name)
        pwd2 = getpass.getpass("repeat password for %s: " % user.name)
        if pwd != pwd2:
            log.error("password don't match")
        else:
            break
    else:
        log.error("no password set")
        return 1
    user.modify(password=pwd)


class RemoveValue(object):
    """ Marker object for index configuration keys to remove. """


class ModelException(Exception):
    """ Base Exception. """
    def __init__(self, msg, *args):
        if args:
            msg = msg % args
        self.msg = msg
        Exception.__init__(self, msg)


class InvalidUser(ModelException):
    """ If a username is invalid or already in use. """


class InvalidIndex(ModelException):
    """ If a indexname is invalid or already in use. """


class ReadonlyIndex(ModelException):
    """ If a indexname is invalid or already in use. """


class NotFound(ModelException):
    """ If a project or version cannot be found. """


class UpstreamError(ModelException):
    """ If an upstream could not be reached or didn't respond correctly. """


class UpstreamNotFoundError(UpstreamError):
    """ If upstream returned a not found error. """


class MissesRegistration(ModelException):
    """ A prior registration of release metadata is required. """


class MissesVersion(ModelException):
    """ A version number is required. """


class NonVolatile(ModelException):
    """ A release is overwritten on a non volatile index. """
    link = None  # the conflicting link


class RootModel:
    """ per-process root model object. """
    def __init__(self, xom):
        self.xom = xom
        self.keyfs = xom.keyfs

    def create_user(self, username, password, email=None, pwhash=None):
        return User.create(self, username, password, email, pwhash=pwhash)

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


def ensure_boolean(value):
    if isinstance(value, bool):
        return value
    if not hasattr(value, "lower"):
        raise InvalidIndexconfig("Unknown boolean value %r." % value)
    if value.lower() in ["false", "no"]:
        return False
    if value.lower() in ["true", "yes"]:
        return True
    raise InvalidIndexconfig("Unknown boolean value '%s'." % value)


def ensure_list(data):
    if isinstance(data, (list, tuple, set)):
        return list(data)
    if not hasattr(data, "split"):
        raise InvalidIndexconfig("Unknown list value %r." % data)
    # split and remove empty
    return list(filter(None, (x.strip() for x in data.split(","))))


def ensure_acl_list(data):
    data = ensure_list(data)
    for index, name in enumerate(data):
        if name.upper() in (':ANONYMOUS:', ':AUTHENTICATED:'):
            data[index] = name.upper()
    return data


def normalize_whitelist_name(name):
    if name == '*':
        return name
    return normalize_name(name)


def get_stage_customizer_classes(xom):
    customizer_classes = sum(
        xom.config.hook.devpiserver_get_stage_customizer_classes(),
        [])
    return dict(customizer_classes)


def get_stage_customizer_class(xom, index_type):
    index_customizers = get_stage_customizer_classes(xom)
    cls = index_customizers.get(index_type)
    if cls is None:
        threadlog.warn("unknown index type %r" % index_type)
        cls = UnknownCustomizer
    if not issubclass(cls, BaseStageCustomizer):
        # we add the BaseStageCustomizer here to keep plugins simpler
        cls = type(
            cls.__name__,
            (cls, BaseStageCustomizer),
            dict(cls.__dict__))
    cls.InvalidIndex = InvalidIndex
    cls.InvalidIndexconfig = InvalidIndexconfig
    cls.ReadonlyIndex = ReadonlyIndex
    return cls


name_char_blocklist_regexp = re.compile(
    r'[\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f'
    r'\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f'
    r' !"#$%&\'()*+,/:;<=>?\[\\\\\]^`{|}~]')


def is_valid_name(name):
    return not name_char_blocklist_regexp.search(name)


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
    def create(cls, model, username, password, email, pwhash=None):
        userlist = model.keyfs.USERLIST.get(readonly=False)
        if username in userlist:
            raise InvalidUser("username '%s' already exists" % username)
        if not is_valid_name(username):
            raise InvalidUser(
                "username '%s' contains characters that aren't allowed. "
                "Any ascii symbol besides -.@_ is blocked." % username)
        user = cls(model, username)
        with user.key.update() as userconfig:
            if password is not None or pwhash:
                user._setpassword(userconfig, password, pwhash=pwhash)
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

    def modify(self, password=None, **kwargs):
        with self.key.update() as userconfig:
            modified = []
            if password is not None:
                self._setpassword(userconfig, password)
                modified.append("password=*******")
                kwargs['pwsalt'] = None
            for key, value in kwargs.items():
                key = ensure_unicode(key)
                if key == 'username':
                    continue
                if value:
                    userconfig[key] = value
                elif key in userconfig:
                    del userconfig[key]
                if key in ('pwsalt', 'pwhash') and value:
                    value = "*******"
                modified.append("%s=%s" % (key, value))
            threadlog.info("modified user %r: %s", self.name,
                           ", ".join(modified))

    def _setpassword(self, userconfig, password, pwhash=None):
        if pwhash:
            userconfig["pwhash"] = ensure_unicode(pwhash)
        else:
            userconfig["pwhash"] = hash_password(password)
        threadlog.info("setting password for user %r", self.name)

    def delete(self):
        # delete all projects on the index
        userconfig = self.get()
        for name in list(userconfig.get("indexes", {})):
            self.getstage(name).delete()
        # delete the user information itself
        self.key.delete()
        with self.keyfs.USERLIST.update() as userlist:
            userlist.remove(self.name)

    def validate(self, password):
        userconfig = self.key.get()
        if not userconfig:
            return False
        salt = userconfig.get("pwsalt")
        pwhash = userconfig["pwhash"]
        valid, newhash = verify_and_update_password_hash(password, pwhash, salt)
        if valid:
            if newhash:
                self.modify(pwsalt=None, pwhash=newhash)
            return True
        return False

    def get(self, credentials=False):
        d = get_mutable_deepcopy(self.key.get())
        if not d:
            return d
        if not credentials:
            d.pop("pwsalt", None)
            d.pop("pwhash", None)
        d["username"] = self.name
        return d

    def create_stage(self, index, type="stage", **kwargs):
        if index in self.get().get("indexes", {}):
            raise InvalidIndex("indexname '%s' already exists" % index)
        if not is_valid_name(index):
            raise InvalidIndex(
                "indexname '%s' contains characters that aren't allowed. "
                "Any ascii symbol besides -.@_ is blocked." % index)
        stage = self._getstage(index, type, {"type": type})
        if isinstance(stage.customizer, UnknownCustomizer):
            raise InvalidIndexconfig("unknown index type %r" % type)
        stage._modify(**kwargs)
        threadlog.info("created index %s: %s", stage.name, stage.ixconfig)
        return stage

    def _getstage(self, indexname, index_type, ixconfig):
        if index_type == "mirror":
            from .extpypi import PyPIStage
            cls = PyPIStage
        else:
            cls = PrivateStage
        customizer_cls = get_stage_customizer_class(self.xom, index_type)
        return cls(
            self.xom,
            username=self.name, index=indexname,
            ixconfig=ixconfig,
            customizer_cls=customizer_cls)

    def getstage(self, indexname):
        ixconfig = self.get()["indexes"].get(indexname, {})
        if not ixconfig:
            return None
        return self._getstage(indexname, ixconfig["type"], ixconfig)


class InvalidIndexconfig(Exception):
    def __init__(self, messages):
        if isinstance(messages, py.builtin._basestring):
            messages = [messages]
        self.messages = messages
        Exception.__init__(self, messages)


def get_principals(value):
    from pyramid.security import Authenticated, Everyone
    principals = set(value)
    if ':AUTHENTICATED:' in principals:
        principals.remove(':AUTHENTICATED:')
        principals.add(Authenticated)
    if ':ANONYMOUS:' in principals:
        principals.remove(':ANONYMOUS:')
        principals.add(Everyone)
    return principals


class BaseStageCustomizer(object):
    readonly = False

    def __init__(self, stage):
        self.stage = stage

    # get_principals_for_* methods for each of the following permissions:
    # pypi_submit, toxresult_upload, index_delete, index_modify,
    # del_entry, del_project, del_verdata
    # also see __acl__ method of BaseStage

    def get_principals_for_pypi_submit(self, restrict_modify=None):
        return self.stage.ixconfig.get("acl_upload", [])

    def get_principals_for_toxresult_upload(self, restrict_modify=None):
        return self.stage.ixconfig.get("acl_toxresult_upload", [':ANONYMOUS:'])

    def get_principals_for_index_delete(self, restrict_modify=None):
        if restrict_modify is None:
            modify_principals = set(['root', self.stage.username])
        else:
            modify_principals = restrict_modify
        return modify_principals

    get_principals_for_index_modify = get_principals_for_index_delete

    def get_principals_for_del_entry(self, restrict_modify=None):
        modify_principals = set(self.stage.ixconfig.get("acl_upload", []))
        if restrict_modify is None:
            modify_principals.update(['root', self.stage.username])
        else:
            modify_principals.update(restrict_modify)
        return modify_principals

    get_principals_for_del_project = get_principals_for_del_entry
    get_principals_for_del_verdata = get_principals_for_del_entry

    def get_possible_indexconfig_keys(self):
        """ Returns all possible custom index config keys.

        These are in addition to the existing keys of a regular private index.
        """
        return ()

    def get_default_config_items(self):
        """ Returns a list of defaults as key/value tuples.

        Only applies to new keys, not existing options of a private index.
        """
        return ()

    def normalize_indexconfig_value(self, key, value):
        """ Returns value normalized to the type stored in the database.

            A return value of None is treated as an error.
            Can raise InvalidIndexconfig.
            Will only be called for custom options, not for existing options
            of a private index.
            """
        return ()

    def validate_config(self, oldconfig, newconfig):
        """ Validates the index config.

            Can raise InvalidIndexconfig."""
        pass

    def on_modified(self, request, oldconfig):
        """ Called after index was created or modified via a request.

            Can do further changes in the current transaction.

            Must use request.apifatal method to indicate errors instead
            of raising HTTPException responses.

            Other exceptions will be handled."""
        pass

    def get_projects_filter_iter(self, projects):
        """ Called when a list of projects is returned.

            Returns None for no filtering, or an iterator returning
            True for items to keep and False for items to remove."""
        return None

    def get_versions_filter_iter(self, project, versions):
        """ Called when a list of versions is returned.

            Returns None for no filtering, or an iterator returning
            True for items to keep and False for items to remove."""
        return None

    def get_simple_links_filter_iter(self, project, links):
        """ Called when a list of simple links is returned.

            Returns None for no filtering, or an iterator returning
            True for items to keep and False for items to remove."""
        return None


class UnknownCustomizer(BaseStageCustomizer):
    readonly = True

    # prevent uploads and deletions besides complete index removal
    def get_principals_for_index_modify(self, restrict_modify=None):
        return []

    get_principals_for_pypi_submit = get_principals_for_index_modify
    get_principals_for_toxresult_upload = get_principals_for_index_modify
    get_principals_for_del_entry = get_principals_for_index_modify
    get_principals_for_del_project = get_principals_for_index_modify
    get_principals_for_del_verdata = get_principals_for_index_modify


class BaseStage(object):
    InvalidIndex = InvalidIndex
    InvalidIndexconfig = InvalidIndexconfig
    InvalidUser = InvalidUser
    NotFound = NotFound
    UpstreamError = UpstreamError
    UpstreamNotFoundError = UpstreamNotFoundError
    MissesRegistration = MissesRegistration
    MissesVersion = MissesVersion
    NonVolatile = NonVolatile

    def __init__(self, xom, username, index, ixconfig, customizer_cls):
        self.xom = xom
        self.username = username
        self.index = index
        self.name = username + "/" + index
        self.ixconfig = ixconfig
        self.customizer = customizer_cls(self)
        # the following attributes are per-xom singletons
        self.model = xom.model
        self.keyfs = xom.keyfs
        self.filestore = xom.filestore

    def get_indexconfig_from_kwargs(self, **kwargs):
        """Normalizes values and validates keys.

        Returns the parts touched by kwargs as dict.
        This is not the complete index configuration."""
        index_type = self.ixconfig['type']
        ixconfig = {}
        # get known keys and validate them
        stage_keys = set(self.get_possible_indexconfig_keys())
        customizer_keys = set(self.customizer.get_possible_indexconfig_keys())
        conflicting = stage_keys.intersection(customizer_keys)
        if conflicting:
            raise ValueError(
                "The stage customizer for '%s' defines keys which conflict "
                "with existing index configuration keys: %s"
                % (index_type, ", ".join(sorted(conflicting))))
        # get default values from the stage class
        for key, value in self.get_default_config_items():
            if kwargs.get(key) is RemoveValue:
                raise InvalidIndexconfig("Default values can't be removed.")
            # if current ixconfig already has the value, use that
            value = self.ixconfig.get(key, value)
            kwargs.setdefault(key, value)
        # now process any key known by the stage class
        for key in stage_keys:
            if key not in kwargs:
                continue
            value = kwargs.pop(key)
            if value is not RemoveValue:
                value = self.normalize_indexconfig_value(key, value)
                if value is None:
                    raise ValueError(
                        "The key '%s' wasn't processed."
                        % (key))
            ixconfig[key] = value
        # next get defaults from the customizer class
        for key, value in self.customizer.get_default_config_items():
            if kwargs.get(key) is RemoveValue:
                raise InvalidIndexconfig("Default values can't be removed.")
            # if current ixconfig already has the value, use that
            value = self.ixconfig.get(key, value)
            kwargs.setdefault(key, value)
        # and process any key known by the customizer class
        for key in customizer_keys:
            if key not in kwargs:
                continue
            value = kwargs.pop(key)
            if value is not RemoveValue:
                value = self.customizer.normalize_indexconfig_value(key, value)
                if value is None:
                    raise ValueError(
                        "The key '%s' wasn't processed."
                        % (key))
            ixconfig[key] = value
        # lastly we get additional default from the hook
        hooks = self.xom.config.hook
        for defaults in hooks.devpiserver_indexconfig_defaults(index_type=index_type):
            conflicting = stage_keys.intersection(defaults)
            if conflicting:
                raise ValueError(
                    "A plugin returned the following keys which conflict with "
                    "existing index configuration keys for '%s': %s"
                    % (index_type, ", ".join(sorted(conflicting))))
            for key, value in defaults.items():
                ixconfig.setdefault(key, kwargs.pop(key, value))
        # XXX backward compatibility for old exports where these could appear
        # on mirror indexes
        # and pypi_whitelist also still needs to be here for existing dbs
        # which didn't have an export/import cycle
        for key in ("bases", "acl_upload", "mirror_whitelist", "pypi_whitelist"):
            kwargs.pop(key, None)
        # remove obsolete pypi_whitelist setting if it exists in original config
        if "pypi_whitelist" in self.ixconfig:
            kwargs["pypi_whitelist"] = RemoveValue
        for key, value in list(kwargs.items()):
            if value is RemoveValue:
                ixconfig[key] = kwargs.pop(key)
        if kwargs:
            raise InvalidIndexconfig(
                ["indexconfig got unexpected keyword arguments: %s"
                 % ", ".join("%s=%s" % x for x in kwargs.items())])
        ixconfig["type"] = index_type
        return ixconfig

    @cached_property
    def user(self):
        # only few methods need the user object.
        return self.model.get_user(self.username)

    def get(self):
        userconfig = self.user.get()
        return userconfig.get("indexes", {}).get(self.index)

    def delete(self):
        with self.user.key.update() as userconfig:
            indexes = userconfig.get("indexes", {})
            if self.index not in indexes:
                threadlog.info("index %s not exists" % self.index)
                return False
            del indexes[self.index]

    def key_projsimplelinks(self, project):
        return self.keyfs.PROJSIMPLELINKS(user=self.username,
            index=self.index, project=normalize_name(project))

    def get_releaselinks(self, project):
        # compatibility access method used by devpi-web and tests
        project = normalize_name(project)
        try:
            return [self._make_elink(project, key, href, require_python)
                    for key, href, require_python in self.get_simplelinks(project)]
        except self.UpstreamNotFoundError:
            return []

    def get_releaselinks_perstage(self, project):
        # compatibility access method for devpi-findlinks and possibly other plugins
        project = normalize_name(project)
        return [self._make_elink(project, key, href, require_python)
                for key, href, require_python in self.get_simplelinks_perstage(project)]

    def _make_elink(self, project, key, href, require_python):
        rp = SimplelinkMeta((key, href, require_python))
        linkdict = {"entrypath": rp._url.path, "hash_spec": rp._url.hash_spec,
                    "require_python": require_python}
        return ELink(self.filestore, linkdict, project, rp.version)

    def get_linkstore_perstage(self, name, version, readonly=True):
        if self.customizer.readonly and not readonly:
            threadlog.warn("index is marked read only")
        return LinkStore(self, name, version, readonly=readonly)

    def get_link_from_entrypath(self, entrypath):
        entry = self.xom.filestore.get_file_entry(entrypath)
        if entry.project is None:
            return None
        linkstore = self.get_linkstore_perstage(entry.project,
                                                entry.version)
        links = linkstore.get_links(entrypath=entrypath)
        assert len(links) < 2
        return links[0] if links else None

    def store_toxresult(self, link, toxresultdata):
        if self.customizer.readonly:
            raise ReadonlyIndex("index is marked read only")
        assert isinstance(toxresultdata, dict), toxresultdata
        linkstore = self.get_linkstore_perstage(link.project, link.version, readonly=False)
        return linkstore.new_reflink(
                rel="toxresult",
                file_content=json.dumps(toxresultdata).encode("utf-8"),
                for_entrypath=link)

    def get_toxresults(self, link):
        l = []
        linkstore = self.get_linkstore_perstage(link.project, link.version)
        for reflink in linkstore.get_links(rel="toxresult", for_entrypath=link):
            data = reflink.entry.file_get_content().decode("utf-8")
            l.append(json.loads(data))
        return l

    def filter_versions(self, project, versions):
        iterator = self.customizer.get_versions_filter_iter(project, versions)
        if iterator is None:
            return versions
        return frozenset(apply_filter_iter(versions, iterator))

    def list_versions(self, project):
        assert py.builtin._istext(project), "project %r not text" % project
        versions = set()
        for stage, res in self.op_sro_check_mirror_whitelist(
                "list_versions_perstage", project=project):
            versions.update(res)
        return self.filter_versions(project, versions)

    def get_latest_version(self, name, stable=False):
        return get_latest_version(
            self.filter_versions(
                name, self.list_versions(name)),
            stable=stable)

    def get_latest_version_perstage(self, name, stable=False):
        return get_latest_version(
            self.filter_versions(
                name, self.list_versions_perstage(name)),
            stable=stable)

    def get_last_project_change_serial_perstage(self, project, at_serial=None):
        tx = self.keyfs.tx
        if at_serial is None:
            at_serial = tx.at_serial
        info = tx.get_last_serial_and_value_at(
            self.key_projects,
            at_serial, raise_on_error=False)
        if info is None:
            # never existed
            return -1
        (last_serial, projects) = info
        if projects is None:
            # the whole index was deleted
            return -1
        info = tx.get_last_serial_and_value_at(
            self.key_projversions(project),
            at_serial, raise_on_error=False)
        if info is None:
            if project in projects:
                # no versions ever existed, but the project is known
                return last_serial
            # the project never existed or was deleted and didn't have versions
            return -1
        (last_serial, versions) = info
        if versions is None:
            # was deleted
            return last_serial
        version = get_latest_version(versions)
        info = tx.get_last_serial_and_value_at(
            self.key_projversion(project, version),
            at_serial, raise_on_error=False)
        if info is None:
            # never existed
            return -1
        (version_serial, version) = info
        return max(last_serial, version_serial)

    def get_versiondata(self, project, version):
        assert py.builtin._istext(project), "project %r not text" % project
        result = {}
        if not self.filter_versions(project, [version]):
            return result
        for stage, res in self.op_sro_check_mirror_whitelist(
                "get_versiondata_perstage",
                project=project, version=version):
            if res:
                if not result:
                    result.update(res)
                else:
                    l = result.setdefault("+shadowing", [])
                    l.append(res)
        return result

    def get_simplelinks(self, project, sorted_links=True):
        """ Return list of (key, href) tuples where "href" is a path
        to a file entry with "#" appended hash-specs or egg-ids
        and "key" is usually the basename of the link or else
        the egg-ID if the link points to an egg.
        """
        all_links = []
        seen = set()

        try:
            for stage, res in self.op_sro_check_mirror_whitelist(
                    "get_simplelinks_perstage", project=project):
                iterator = self.customizer.get_simple_links_filter_iter(project, res)
                if iterator is not None:
                    res = apply_filter_iter(res, iterator)
                for key, href, require_python in res:
                    if key not in seen:
                        seen.add(key)
                        all_links.append((key, href, require_python))
        except self.UpstreamNotFoundError:
            return []

        if sorted_links:
            all_links = [(v.key, v.href, v.require_python)
                        for v in sorted(map(SimplelinkMeta, all_links), reverse=True)]
        return all_links

    def get_mirror_whitelist_info(self, project):
        project = ensure_unicode(project)
        private_hit = whitelisted = False
        for stage in self.sro():
            in_index = stage.has_project_perstage(project)
            if stage.ixconfig["type"] == "mirror":
                has_mirror_base = in_index and (not private_hit or whitelisted)
                blocked_by_mirror_whitelist = in_index and private_hit and not whitelisted
                return dict(
                    has_mirror_base=has_mirror_base,
                    blocked_by_mirror_whitelist=stage.name if blocked_by_mirror_whitelist else None)
            private_hit = private_hit or in_index
            whitelist = set(stage.ixconfig.get("mirror_whitelist", set()))
            whitelisted = whitelisted or '*' in whitelist or project in whitelist
        return dict(
            has_mirror_base=False,
            blocked_by_mirror_whitelist=None)

    def has_mirror_base(self, project):
        return self.get_mirror_whitelist_info(project)['has_mirror_base']

    def filter_projects(self, projects):
        iterator = self.customizer.get_projects_filter_iter(projects)
        if iterator is None:
            return projects
        return frozenset(apply_filter_iter(projects, iterator))

    def has_project(self, project):
        if not self.filter_projects([project]):
            return False
        for stage, res in self.op_sro("has_project_perstage", project=project):
            if res:
                return True
        return False

    def list_projects(self):
        result = []
        for stage, projects in self.op_sro("list_projects_perstage"):
            result.append((
                stage,
                self.filter_projects(projects)))
        return result

    def _modify(self, **kw):
        if 'type' in kw and self.ixconfig["type"] != kw['type']:
            raise InvalidIndexconfig(
                ["the 'type' of an index can't be changed"])
        kw.pop("type", None)
        kw.pop("projects", None)  # we never modify this from the outside
        ixconfig = self.get_indexconfig_from_kwargs(**kw)
        # modify user/indexconfig
        with self.user.key.update() as userconfig:
            oldconfig = dict(self.ixconfig)
            newconfig = userconfig["indexes"].setdefault(self.index, {})
            for key, value in list(ixconfig.items()):
                if value is RemoveValue:
                    newconfig.pop(key, None)
                    ixconfig.pop(key)
            newconfig.update(ixconfig)
            self.customizer.validate_config(oldconfig, newconfig)
            self.ixconfig = newconfig
            return newconfig

    def modify(self, index=None, **kw):
        if self.customizer.readonly:
            raise ReadonlyIndex("index is marked read only")
        newconfig = self._modify(**kw)
        threadlog.info("modified index %s: %s", self.name, newconfig)
        return newconfig

    def op_sro(self, opname, **kw):
        if "project" in kw:
            project = normalize_name(kw["project"])
            if not self.filter_projects([project]):
                return
        for stage in self.sro():
            yield stage, getattr(stage, opname)(**kw)

    def op_sro_check_mirror_whitelist(self, opname, **kw):
        project = normalize_name(kw["project"])
        if not self.filter_projects([project]):
            return
        whitelisted = private_hit = False
        for stage in self.sro():
            if stage.ixconfig["type"] == "mirror":
                if private_hit:
                    if not whitelisted:
                        threadlog.debug("%s: private package %r not whitelisted, "
                                        "ignoring %s", opname, project, stage.name)
                        continue
                    threadlog.debug("private package %r whitelisted at stage %s",
                                    project, whitelisted.name)
            else:
                whitelist = set(stage.ixconfig.get("mirror_whitelist", set()))
                if '*' in whitelist or project in whitelist:
                    whitelisted = stage
                elif stage.has_project_perstage(project):
                    private_hit = True

            try:
                if not stage.has_project_perstage(project):
                    continue
                res = getattr(stage, opname)(**kw)
                private_hit = private_hit or res
                yield stage, res
            except self.UpstreamError as exc:
                # If we are currently checking ourself raise the error, it is fatal
                if stage is self:
                    raise
                threadlog.warn('Failed to check mirror whitelist. Assume it does not exists (%s)', exc)

    def sro(self):
        """ return stage resolution order. """
        todo = [self]
        todo_mirrors = []
        seen = set()
        while todo:
            stage = todo.pop(0)
            yield stage
            seen.add(stage.name)
            for base in stage.ixconfig.get("bases", ()):
                current_stage = self.model.getstage(base)
                if current_stage is None:
                    threadlog.warn(
                        "Index %s refers to non-existing base %s.",
                        self.name, base)
                    continue
                if base not in seen:
                    if current_stage.ixconfig['type'] == 'mirror':
                        todo_mirrors.append(current_stage)
                    else:
                        todo.append(current_stage)
        for stage in todo_mirrors:
            yield stage

    def __acl__(self):
        from pyramid.security import Allow

        permissions = (
            'pypi_submit',
            'toxresult_upload',
            'index_delete',
            'index_modify',
            'del_entry',
            'del_project',
            'del_verdata')
        restrict_modify = self.xom.config.restrict_modify
        acl = []
        for permission in permissions:
            method = getattr(self.customizer, 'get_principals_for_%s' % permission)
            for principal in get_principals(method(restrict_modify=restrict_modify)):
                acl.append((Allow, principal, permission))
        return acl


class PrivateStage(BaseStage):
    metadata_keys = (
        'name', 'version',
        # additional meta-data
        'metadata_version', 'summary', 'home_page', 'author', 'author_email',
        'maintainer', 'maintainer_email', 'license', 'description',
        'keywords', 'platform', 'classifiers', 'download_url',
        'supported_platform', 'comment',
        # PEP 314
        'provides', 'requires', 'obsoletes',
        # Metadata 1.2
        'project_urls', 'provides_dist', 'obsoletes_dist',
        'requires_dist', 'requires_external', 'requires_python',
        # Metadata 2.1
        'description_content_type', 'provides_extras')
    metadata_list_fields = (
        'platform', 'classifiers', 'obsoletes',
        'requires', 'provides', 'obsoletes_dist',
        'provides_dist', 'requires_dist', 'requires_external',
        'project_urls', 'supported_platform', 'setup_requires_dist',
        'provides_extra', 'extension')

    use_external_url = False

    def __init__(self, xom, username, index, ixconfig, customizer_cls):
        super(PrivateStage, self).__init__(
            xom, username, index, ixconfig, customizer_cls)
        self.key_projects = self.keyfs.PROJNAMES(user=username, index=index)

    def get_possible_indexconfig_keys(self):
        return tuple(dict(self.get_default_config_items())) + (
            "custom_data", "description", "title")

    def get_default_config_items(self):
        return [
            ("volatile", True),
            ("acl_upload", [self.username]),
            ("acl_toxresult_upload", [":ANONYMOUS:"]),
            ("bases", ()),
            ("mirror_whitelist", [])]

    def normalize_indexconfig_value(self, key, value):
        if key == "volatile":
            return ensure_boolean(value)
        if key == "bases":
            return normalize_bases(
                self.xom.model, ensure_list(value))
        if key == "acl_upload":
            return ensure_acl_list(value)
        if key == "acl_toxresult_upload":
            return ensure_acl_list(value)
        if key == "mirror_whitelist":
            return [
                normalize_whitelist_name(x)
                for x in ensure_list(value)]
        if key in ("custom_data", "description", "title"):
            return value

    def delete(self):
        # delete all projects on this index
        for name in self.list_projects_perstage():
            self.del_project(name)
        BaseStage.delete(self)

    #
    # registering project and version metadata
    #

    def set_versiondata(self, metadata):
        """ register metadata.  Raises ValueError in case of metadata
        errors. """
        if self.customizer.readonly:
            raise ReadonlyIndex("index is marked read only")
        validate_metadata(metadata)
        self._set_versiondata(metadata)

    def key_projversions(self, project):
        return self.keyfs.PROJVERSIONS(user=self.username,
            index=self.index, project=normalize_name(project))

    def key_projversion(self, project, version):
        return self.keyfs.PROJVERSION(
            user=self.username, index=self.index,
            project=normalize_name(project), version=version)

    def _set_versiondata(self, metadata):
        project = normalize_name(metadata["name"])
        version = metadata["version"]
        key_projversion = self.key_projversion(project, version)
        versiondata = key_projversion.get(readonly=False)
        versiondata.update(metadata)
        key_projversion.set(versiondata)
        threadlog.info("set_metadata %s-%s", project, version)
        versions = self.key_projversions(project).get(readonly=False)
        if version not in versions:
            versions.add(version)
            self.key_projversions(project).set(versions)
        self.add_project_name(project)

    def add_project_name(self, project):
        project = normalize_name(project)
        projects = self.key_projects.get(readonly=False)
        if project not in projects:
            if self.customizer.readonly:
                raise ReadonlyIndex("index is marked read only")
            projects.add(project)
            self.key_projects.set(projects)

    def del_project(self, project):
        project = normalize_name(project)
        for version in list(self.key_projversions(project).get()):
            self.del_versiondata(project, version, cleanup=False)
        self._regen_simplelinks(project)
        with self.key_projects.update() as projects:
            projects.remove(project)
        threadlog.info("deleting project %s", project)
        self.key_projversions(project).delete()

    def del_versiondata(self, project, version, cleanup=True):
        project = normalize_name(project)
        if not self.has_project_perstage(project):
            raise self.NotFound("project %r not found on stage %r" %
                                (project, self.name))
        versions = self.key_projversions(project).get(readonly=False)
        if version not in versions:
            raise self.NotFound("version %r of project %r not found on stage %r" %
                                (version, project, self.name))
        linkstore = self.get_linkstore_perstage(project, version, readonly=False)
        linkstore.remove_links()
        versions.remove(version)
        self.key_projversion(project, version).delete()
        self.key_projversions(project).set(versions)
        if cleanup:
            if not versions:
                self.del_project(project)
            self._regen_simplelinks(project)

    def del_entry(self, entry, cleanup=True):
        # we need to store project and version for use in cleanup part below
        project = entry.project
        version = entry.version
        linkstore = self.get_linkstore_perstage(
            project, version, readonly=False)
        linkstore.remove_links(basename=entry.basename)
        entry.delete()
        if cleanup:
            if not linkstore.get_links():
                self.del_versiondata(project, version)
            self._regen_simplelinks(project)

    def list_versions_perstage(self, project):
        return self.key_projversions(project).get()

    def get_versiondata_perstage(self, project, version, readonly=True):
        project = normalize_name(project)
        return self.key_projversion(project, version).get(readonly=readonly)

    def get_simplelinks_perstage(self, project):
        data = self.key_projsimplelinks(project).get()
        links = data.get("links", [])
        requires_python = data.get("requires_python", [])
        return join_requires(links, requires_python)

    def _regen_simplelinks(self, project_input):
        project = normalize_name(project_input)
        links = []
        requires_python = []
        for version in self.list_versions_perstage(project):
            linkstore = self.get_linkstore_perstage(project, version)
            releases = linkstore.get_links("releasefile")
            links.extend(map(make_key_and_href, releases))
            require_python = self.get_versiondata_perstage(project,
                    version).get('requires_python')
            requires_python.extend([require_python] * len(releases))
        data_dict = {u"links":links, u"requires_python":requires_python}
        self.key_projsimplelinks(project).set(data_dict)

    def list_projects_perstage(self):
        return self.key_projects.get()

    def has_project_perstage(self, project):
        return normalize_name(project) in self.list_projects_perstage()

    def store_releasefile(self, project, version, filename, content,
                          last_modified=None):
        if self.customizer.readonly:
            raise ReadonlyIndex("index is marked read only")
        project = normalize_name(project)
        filename = ensure_unicode(filename)
        if not self.get_versiondata_perstage(project, version):
            # There's a chance the version was guessed from the
            # filename, which might have swapped dashes to underscores
            if '_' in version:
                version = version.replace('_', '-')
                if not self.get_versiondata_perstage(project, version):
                    raise MissesRegistration("%s-%s", project, version)
            else:
                raise MissesRegistration("%s-%s", project, version)
        linkstore = self.get_linkstore_perstage(project, version, readonly=False)
        link = linkstore.create_linked_entry(
                rel="releasefile",
                basename=filename,
                file_content=content,
                last_modified=last_modified)
        self._regen_simplelinks(project)
        return link

    def store_doczip(self, project, version, content):
        if self.customizer.readonly:
            raise ReadonlyIndex("index is marked read only")
        project = normalize_name(project)
        if not version:
            version = self.get_latest_version_perstage(project)
            if not version:
                raise MissesVersion(
                    "doczip has no version and '%s' has no releases to "
                    "derive one from", project)
            threadlog.info("store_doczip: derived version of %s is %s",
                           project, version)
        basename = "%s-%s.doc.zip" % (project, version)
        verdata = self.get_versiondata_perstage(
            project, version, readonly=False)
        if not verdata:
            self.set_versiondata({'name': project, 'version': version})
        linkstore = self.get_linkstore_perstage(project, version, readonly=False)
        link = linkstore.create_linked_entry(
                rel="doczip",
                basename=basename,
                file_content=content,
        )
        return link

    def get_doczip_entry(self, project, version):
        """ get entry of documentation zip or None if no docs exists. """
        linkstore = self.get_linkstore_perstage(project, version)
        links = linkstore.get_links(rel="doczip")
        if links:
            if len(links) > 1:
                threadlog.warn("Multiple documentation files for %s-%s, returning newest",
                               project, version)
            link = links[-1]
            return link.entry

    def get_doczip(self, project, version):
        """ get documentation zip content or None if no docs exists. """
        entry = self.get_doczip_entry(project, version)
        if entry is not None:
            return entry.file_get_content()

    def get_last_change_serial_perstage(self, at_serial=None):
        tx = self.keyfs.tx
        if at_serial is None:
            at_serial = tx.at_serial
        try:
            (last_serial, projects) = tx.get_last_serial_and_value_at(
                self.key_projects, at_serial)
        except KeyError:
            last_serial = -1
            projects = ()
        if last_serial >= at_serial:
            return last_serial
        for project in projects:
            (versions_serial, versions) = tx.get_last_serial_and_value_at(
                self.key_projversions(project), at_serial)
            last_serial = max(last_serial, versions_serial)
            if last_serial >= at_serial:
                return last_serial
            for version in versions:
                (version_serial, version) = tx.get_last_serial_and_value_at(
                    self.key_projversion(project, version), at_serial)
                last_serial = max(last_serial, version_serial)
                if last_serial >= at_serial:
                    return last_serial
        # no project uploaded yet
        user_key = self.user.key
        (user_serial, user_config) = tx.get_last_serial_and_value_at(
            user_key, at_serial)
        try:
            current_index_config = user_config["indexes"][self.index]
        except KeyError:
            raise KeyError("The index '%s' was not commited yet." % self.index)
        # if any project is newer than the user config, we are done
        if last_serial >= user_serial:
            return last_serial
        relpath = user_key.relpath
        for serial, user_config in tx.iter_serial_and_value_backwards(relpath, user_serial):
            if user_serial < last_serial:
                break
            index_config = get_mutable_deepcopy(
                user_config["indexes"].get(self.index, {}))
            if current_index_config == index_config:
                user_serial = serial
                continue
            last_serial = user_serial
            break
        return last_serial

    # BBB old name for backward compatibility, remove with 6.0.0
    def get_last_change_serial(self, at_serial=None):
        import warnings
        warnings.warn(
            "The get_last_change_serial method is deprecated, "
            "use get_last_change_serial_perstage instead",
            DeprecationWarning)
        return self.get_last_change_serial_perstage(at_serial=at_serial)


class StageCustomizer(BaseStageCustomizer):
    pass


@hookimpl
def devpiserver_get_stage_customizer_classes():
    # prevent plugins from installing their own under the reserved names
    return [
        ("stage", StageCustomizer)]


class ELink(object):
    """ model Link using entrypathes for referencing. """
    def __init__(self, filestore, linkdict, project, version):
        self.filestore = filestore
        self.linkdict = linkdict
        self.basename = posixpath.basename(self.entrypath)
        self.project = project
        self.version = version
        if sys.version_info < (3,0):
            for key in linkdict:
                assert py.builtin._istext(key)

    @property
    def relpath(self):
        return self.linkdict["entrypath"]

    @property
    def hash_spec(self):
        return self.linkdict.get("hash_spec", "")

    @property
    def hash_value(self):
        return self.hash_spec.split("=")[1]

    @property
    def hash_type(self):
        return self.hash_spec.split("=")[0]

    def matches_checksum(self, content):
        hash_algo, hash_value = parse_hash_spec(self.hash_spec)
        if not hash_algo:
            return True
        return hash_algo(content).hexdigest() == hash_value

    def __getattr__(self, name):
        try:
            return self.linkdict[name]
        except KeyError:
            if name in ("for_entrypath", "rel"):
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
        return list(getattr(self, '_log', []))


class LinkStore:
    def __init__(self, stage, project, version, readonly=True):
        self.stage = stage
        self.filestore = stage.filestore
        self.project = normalize_name(project)
        self.version = version
        self.verdata = stage.get_versiondata_perstage(self.project, version, readonly=readonly)
        if not self.verdata:
            raise MissesRegistration("%s-%s on stage %s",
                                     project, version, stage.name)

    @property
    def metadata(self):
        metadata = {}
        for k, v in get_mutable_deepcopy(self.verdata).items():
            if not k.startswith("+"):
                metadata[k] = v
        return metadata

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
        timestamp = strftime("%Y%m%d%H%M%S", gmtime())
        filename = "%s.%s-%s-%d" % (
            base_entry.basename, rel, timestamp, len(other_reflinks))
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
        return list(filter(fil, [ELink(self.filestore, linkdict, self.project, self.version)
                           for linkdict in self.verdata.get("+elinks", [])]))

    def _create_file_entry(self, basename, file_content, ref_hash_spec=None):
        entry = self.filestore.store(
                    user=self.stage.username, index=self.stage.index,
                    basename=basename,
                    file_content=file_content,
                    dir_hash_spec=ref_hash_spec)
        entry.project = self.project
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
        return ELink(self.filestore, new_linkdict, self.project,
                     self.version)


class SimplelinkMeta(CompareMixin):
    """ helper class to provide information for items from get_simplelinks() """
    def __init__(self, key_href):
        self.key, self.href, self.require_python = key_href
        self._url = URL(self.href)
        self.name, self.version, self.ext = splitbasename(self._url.basename, checkarch=False)

    @cached_property
    def cmpval(self):
        return parse_version(self.version), normalize_name(self.name), self.ext


def make_key_and_href(entry):
    # entry is either an ELink or a filestore.FileEntry instance.
    # both provide a "relpath" attribute which points to a file entry.
    href = entry.relpath
    if entry.hash_spec:
        href += "#" + entry.hash_spec
    return entry.basename, href


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
    return tuple(newbases)


def add_keys(xom, keyfs):
    # users and index configuration
    keyfs.add_key("USER", "{user}/.config", dict)
    keyfs.add_key("USERLIST", ".config", set)

    # type mirror related data
    keyfs.add_key("PYPIFILE_NOMD5", "{user}/{index}/+e/{dirname}/{basename}", dict)
    keyfs.add_key("MIRRORNAMESINIT", "{user}/{index}/.mirrornameschange", int)

    # type "stage" related
    keyfs.add_key("PROJSIMPLELINKS", "{user}/{index}/{project}/.simple", dict)
    keyfs.add_key("PROJVERSIONS", "{user}/{index}/{project}/.versions", set)
    keyfs.add_key("PROJVERSION", "{user}/{index}/{project}/{version}/.config", dict)
    keyfs.add_key("PROJNAMES", "{user}/{index}/.projects", set)
    keyfs.add_key("STAGEFILE",
                  "{user}/{index}/+f/{hashdir_a}/{hashdir_b}/{filename}", dict)

    sub = EventSubscribers(xom)
    keyfs.PROJVERSION.on_key_change(sub.on_changed_version_config)
    keyfs.STAGEFILE.on_key_change(sub.on_changed_file_entry)
    keyfs.MIRRORNAMESINIT.on_key_change(sub.on_mirror_initialnames)
    keyfs.USER.on_key_change(sub.on_userchange)


class EventSubscribers:
    """ the 'on_' functions are called within in the notifier thread. """
    def __init__(self, xom):
        self.xom = xom

    def on_changed_version_config(self, ev):
        """ when version config is changed for a project in a stage"""
        params = ev.typedkey.params
        user = params["user"]
        index = params["index"]
        keyfs = self.xom.keyfs
        hook = self.xom.config.hook
        with keyfs.transaction(write=False, at_serial=ev.at_serial) as tx:
            # find out if metadata changed
            if ev.back_serial == -1:
                old = {}
            else:
                assert ev.back_serial < ev.at_serial
                try:
                    old = tx.get_value_at(ev.typedkey, ev.back_serial)
                except KeyError:
                    old = {}

            # XXX slightly flaky logic for detecting metadata changes
            metadata = ev.value
            source = metadata or old
            project, version = source["name"], source["version"]
            if metadata != old:
                stage = self.xom.model.getstage(user, index)
                hook.devpiserver_on_changed_versiondata(
                    stage=stage, project=project,
                    version=version, metadata=metadata)

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
            entry = FileEntry(ev.typedkey, meta=ev.value)
            if not entry.project or not entry.version:
                # the entry was deleted
                self.xom.config.hook.devpiserver_on_remove_file(
                    stage=stage,
                    relpath=ev.typedkey.relpath
                )
                return
            name = entry.project
            assert name == normalize_name(name)
            linkstore = stage.get_linkstore_perstage(name, entry.version)
            links = linkstore.get_links(basename=entry.basename)
            if len(links) == 1:
                self.xom.config.hook.devpiserver_on_upload(
                    stage=stage, project=name,
                    version=entry.version,
                    link=links[0])

    def on_mirror_initialnames(self, ev):
        """ when projectnames are first loaded into a mirror. """
        params = ev.typedkey.params
        user = params.get("user")
        index = params.get("index")
        keyfs = self.xom.keyfs
        with keyfs.transaction(at_serial=ev.at_serial):
            stage = self.xom.model.getstage(user, index)
            if stage is not None and stage.ixconfig["type"] == "mirror":
                self.xom.config.hook.devpiserver_mirror_initialnames(
                    stage=stage,
                    projectnames=stage.list_projects_perstage()
                )

    def on_userchange(self, ev):
        """ when user data changes. """
        params = ev.typedkey.params
        username = params.get("user")
        keyfs = self.xom.keyfs
        with keyfs.transaction(at_serial=ev.at_serial) as tx:

            if ev.back_serial > -1:
                old = tx.get_value_at(ev.typedkey, ev.back_serial)
                old_indexes = set(old.get("indexes", {}))
            else:
                old_indexes = set()
            threadlog.debug("old indexes: %s", old_indexes)

            user = self.xom.model.get_user(username)
            if user is None:
                # deleted
                return
            userconfig = user.key.get()
            for name in userconfig.get("indexes", {}):
                if name not in old_indexes:
                    stage = user.getstage(name)
                    self.xom.config.hook.devpiserver_stage_created(stage=stage)
