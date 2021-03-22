from __future__ import unicode_literals
import base64
import hashlib
import itsdangerous
import py
import secrets
from .log import threadlog
from passlib.context import CryptContext
from passlib.utils.handlers import MinimalHandler


notset = object()


class AuthException(Exception):
    """ Raised by external plugins in case of an error. """


class Auth:
    LOGIN_EXPIRATION = 60 * 60 * 10  # 10 hours

    class Expired(Exception):
        """ proxy authentication expired. """

    def __init__(self, model, secret):
        self.model = model
        self.serializer = itsdangerous.TimedSerializer(secret)
        self.hook = self.model.xom.config.hook.devpiserver_auth_request
        self.legacy_hook = self.model.xom.config.hook.devpiserver_auth_user

    def _legacy_auth(self, authuser, authpassword, is_root, user):
        results = []
        if not is_root:
            userinfo = user.get() if user is not None else None
            try:
                results = [
                    x for x in self.legacy_hook(
                        userdict=userinfo,
                        username=authuser,
                        password=authpassword)
                    if x["status"] != "unknown"]
            except AuthException:
                threadlog.exception("Error in authentication plugin.")
                return dict(status="nouser")
        if [x for x in results if x["status"] != "ok"]:
            # a plugin discovered invalid credentials or returned an invalid
            # status, so we abort
            return dict(status="reject")
        userinfo_list = [x for x in results if x is not False]
        if userinfo_list and not is_root:
            # one of the plugins returned valid userinfo
            # return union of all groups which may be contained in that info
            groups = (ui.get('groups', []) for ui in userinfo_list)
            return dict(status="ok", groups=sorted(set(sum(groups, []))))

    def _validate(self, authuser, authpassword, request=None):
        """ Validates user credentials.

            If authentication plugins are installed, they will be queried.

            If no user can be found, returns None.
            If the credentials are wrong, returns False.
            On success a list of group names the user is member of will be
            returned. If the plugins don't return any groups, then the list
            will be empty.
            The 'root' user is always authenticated with the devpi-server
            credentials, never by plugins.
        """
        user = self.model.get_user(authuser)
        is_root = authuser == 'root'
        result = None
        if not is_root:
            userinfo = user.get(credentials=True) if user is not None else None
            result = self.hook(request=request, userdict=userinfo, username=authuser, password=authpassword)
            if result is not None:
                if result["status"] != "ok":
                    return dict(status="reject")
                # plugins may never return from_user_object
                result.pop('from_user_object', None)
                return result
        result = self._legacy_auth(authuser, authpassword, is_root, user)
        if result is not None:
            # plugins may never return from_user_object
            result.pop('from_user_object', None)
            return result
        if user is None:
            # we got no user model
            return dict(status="nouser")
        # none of the plugins returned valid groups, check our own data
        # first get a potentially cached value
        result = getattr(request, '__devpiserver_user_validate_result', notset)
        if result is notset:
            result = user.validate(authpassword)
            # cache result on request if available
            if request is not None:
                # we have to use setattr to avoid name mangling of prefix dunder
                setattr(request, '__devpiserver_user_validate_result', result)
        if result:
            return dict(status="ok", from_user_object=True)
        return dict(status="reject")

    def _get_auth_status(self, authuser, authpassword, request=None):
        try:
            val = self.serializer.loads(authpassword, max_age=self.LOGIN_EXPIRATION)
        except itsdangerous.SignatureExpired:
            return dict(status="expired")
        except itsdangerous.BadData:
            # check if we got user/password direct authentication
            return self._validate(authuser, authpassword, request=request)
        else:
            if not isinstance(val, list):
                threadlog.debug("invalid auth token type for user %r", authuser)
                return dict(status="nouser")
            if len(val) != 3:
                threadlog.debug("missing auth token info for user %r", authuser)
                return dict(status="nouser")
            if val[0] != authuser:
                threadlog.debug("auth token username mismatch for user %r", authuser)
                return dict(status="nouser")
            if val[2] and self.model.get_user(authuser) is None:
                threadlog.debug("missing user object for user %r", authuser)
                return dict(status="nouser")
            return dict(status="ok", groups=val[1])

    def new_proxy_auth(self, username, password, request=None):
        result = self._validate(username, password, request=request)
        if result["status"] == "ok":
            pseudopass = self.serializer.dumps([
                username,
                result.get("groups", []),
                result.get("from_user_object", False)])
            assert py.builtin._totext(pseudopass, 'ascii')
            return {"password": pseudopass,
                    "expiration": self.LOGIN_EXPIRATION}


def getpwhash(password, salt):
    hash = hashlib.sha256()
    hash.update(salt.encode("ascii"))
    hash.update(password.encode("utf-8"))
    return py.builtin._totext(hash.hexdigest())


def newsalt():
    return py.builtin._totext(base64.b64encode(secrets.token_bytes(16)), "ascii")


class DevpiHandler(MinimalHandler):
    name = "devpi"
    setting_kwds = ()
    context_kwds = ()

    @classmethod
    def _get_salt_and_hash(cls, hash):
        salt = None
        try:
            (salt, hash) = hash.split(':', 1)
        except ValueError:
            pass
        return (salt, hash)

    @classmethod
    def identify(cls, hash):
        (salt, hash) = cls._get_salt_and_hash(hash)
        return salt and hash

    @classmethod
    def hash(cls, secret, **kwds):
        salt = newsalt()
        hash = getpwhash(secret, salt)
        return "%s:%s" % (salt, hash)

    @classmethod
    def verify(cls, secret, hash):
        (salt, hash) = cls._get_salt_and_hash(hash)
        return salt and hash and (getpwhash(secret, salt) == hash)


pwd_context = CryptContext(schemes=["argon2", DevpiHandler], deprecated="auto")


def verify_and_update_password_hash(password, hash, salt=None):
    if salt is not None:
        hash = "%s:%s" % (salt, hash)
    (valid, newhash) = pwd_context.verify_and_update(password, hash)
    if newhash:
        newhash = py.builtin._totext(newhash)
    return (valid, newhash)


def hash_password(password):
    return py.builtin._totext(pwd_context.hash(password))
