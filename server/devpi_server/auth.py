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
            returned, if no group search is set up, then the list will always
            be empty.
            The 'root' user is always authenticated with the devpi-server
            credentials, never by plugins.
        """
        user = self.model.get_user(authuser)
        results = []
        is_root = authuser == 'root'
        if not is_root:
            try:
                results = [
                    x for x in self.hook(self.model, authuser, authpassword)
                    if x is not None]
            except AuthException as e:
                threadlog.exception("Error in authentication plugin.")
                return None
        if [x for x in results if x is False]:
            # a plugin discovered invalid credentials, so we abort
            return False
        groups_list = [x for x in results if x is not False]
        if groups_list and not is_root:
            # one of the plugins returned valid groups
            # return union of all returned groups
            return list(set(sum(groups_list, [])))
        if user is None:
            # we got no user model
            return None
        # none of the plugins returned valid groups, check our own data
        if user.validate(authpassword):
            return []
        return False

    def _get_auth_groups(self, authuser, authpassword, raising=True):
        try:
            val = self.serializer.loads(authpassword, max_age=self.LOGIN_EXPIRATION)
        except itsdangerous.SignatureExpired:
            if raising:
                raise self.Expired()
            return None
        except itsdangerous.BadData:
            # check if we got user/password direct authentication
            result = self._validate(authuser, authpassword)
            if isinstance(result, list):
                return result
            return None
        else:
            if not isinstance(val, list) or len(val) != 2 or val[0] != authuser:
                threadlog.debug("mismatch credential for user %r", authuser)
                return None
            return val[1]

    def new_proxy_auth(self, username, password):
        result = self._validate(username, password)
        if isinstance(result, list):
            pseudopass = self.serializer.dumps((username, result))
            assert py.builtin._totext(pseudopass, 'ascii')
            return {"password":  pseudopass,
                    "expiration": self.LOGIN_EXPIRATION}

    def get_auth_status(self, userpassword):
        if userpassword is None:
            return ["noauth", ""]
        username, password = userpassword
        try:
            groups = self._get_auth_groups(username, password)
        except self.Expired:
            return ["expired", username]
        if isinstance(groups, list):
            return ["ok", username]
        else:
            return ["nouser", username]



def getpwhash(password, salt):
    hash = hashlib.sha256()
    hash.update(salt.encode("ascii"))
    hash.update(password.encode("utf-8"))
    return hash.hexdigest()

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

