from __future__ import unicode_literals
import base64
import os
import hashlib
import itsdangerous
import py
from .log import threadlog


class AuthException(Exception):
    """ Raised by external plugins in case of an error. """


class Auth:
    LOGIN_EXPIRATION = 60*60*10  # 10 hours

    class Expired(Exception):
        """ proxy authentication expired. """

    def __init__(self, model, secret):
        self.model = model
        self.serializer = itsdangerous.TimedSerializer(secret)
        self.hook = self.model.xom.config.hook.devpiserver_auth_user

    def _validate(self, authuser, authpassword):
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
        results = []
        is_root = authuser == 'root'
        if not is_root:
            userinfo = user.get() if user is not None else None
            try:
                results = [
                    x for x in self.hook(userdict=userinfo,
                                         username=authuser,
                                         password=authpassword)
                    if x["status"] != "unknown"]
            except AuthException:
                threadlog.exception("Error in authentication plugin.")
                return dict(status="nouser")
        if [x for x in results if x["status"] != "ok"]:
            # a plugin discovered invalid credentials or returned an invalid
            # status, so we abort
            return dict(status="nouser")
        userinfo_list = [x for x in results if x is not False]
        if userinfo_list and not is_root:
            # one of the plugins returned valid userinfo
            # return union of all groups which may be contained in that info
            groups = (ui.get('groups', []) for ui in userinfo_list)
            return dict(status="ok", groups=sorted(set(sum(groups, []))))
        if user is None:
            # we got no user model
            return dict(status="nouser")
        # none of the plugins returned valid groups, check our own data
        if user.validate(authpassword):
            return dict(status="ok")
        return dict(status="nouser")

    def _get_auth_status(self, authuser, authpassword):
        try:
            val = self.serializer.loads(authpassword, max_age=self.LOGIN_EXPIRATION)
        except itsdangerous.SignatureExpired:
            return dict(status="expired")
        except itsdangerous.BadData:
            # check if we got user/password direct authentication
            return self._validate(authuser, authpassword)
        else:
            if not isinstance(val, list) or len(val) != 2 or val[0] != authuser:
                threadlog.debug("mismatch credential for user %r", authuser)
                return dict(status="nouser")
            return dict(status="ok", groups=val[1])

    def new_proxy_auth(self, username, password):
        result = self._validate(username, password)
        if result["status"] == "ok":
            pseudopass = self.serializer.dumps(
                (username, result.get("groups", [])))
            assert py.builtin._totext(pseudopass, 'ascii')
            return {"password":  pseudopass,
                    "expiration": self.LOGIN_EXPIRATION}

    def get_auth_status(self, userpassword):
        if userpassword is None:
            return ["noauth", "", []]
        username, password = userpassword
        status = self._get_auth_status(username, password)
        return [status["status"], username, status.get("groups", [])]


def getpwhash(password, salt):
    hash = hashlib.sha256()
    hash.update(salt.encode("ascii"))
    hash.update(password.encode("utf-8"))
    return py.builtin._totext(hash.hexdigest())

def newsalt():
    return py.builtin._totext(base64.b64encode(os.urandom(16)), "ascii")

def verify_password(password, hash, salt):
    if getpwhash(password, salt) == hash:
        return True
    return False

def crypt_password(password):
    salt = newsalt()
    hash = getpwhash(password, salt)
    return salt, hash

