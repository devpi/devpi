from __future__ import unicode_literals
import base64
import os
import hashlib
import itsdangerous
import py
from logging import getLogger
log = getLogger(__name__)

class Auth:
    LOGIN_EXPIRATION = 60*60*10  # 10 hours

    class Expired(Exception):
        """ proxy authentication expired. """

    def __init__(self, db, secret):
        self.db = db
        self.signer = itsdangerous.TimestampSigner(secret)

    def get_auth_user(self, auth, raising=True):
        try:
            authuser, authpassword = auth
        except TypeError:
            return None
        try:
            val = self.signer.unsign(authpassword, self.LOGIN_EXPIRATION)
        except itsdangerous.SignatureExpired:
            if raising:
                raise self.Expired()
            return None
        except itsdangerous.BadData:
            # check if we got user/password direct authentication
            if self.db.user_validate(authuser, authpassword):
                return authuser
            return None
        else:
            if not val.startswith(authuser.encode() + b"-"):
                log.debug("mismatch credential for user %r", authuser)
                return None
            return authuser

    def new_proxy_auth(self, user, password):
        hash = self.db.user_validate(user, password)
        if hash:
            pseudopass = self.signer.sign(user + "-" + hash)
            pseudopass = pseudopass.decode("ascii")
            assert py.builtin._istext(pseudopass)
            return {"password":  pseudopass,
                    "expiration": self.LOGIN_EXPIRATION}

    def get_auth_status(self, userpassword):
        if userpassword is None:
            return ["noauth", ""]
        user, password = userpassword
        if not self.db.user_exists(user):
            return ["nouser", user]
        try:
            self.get_auth_user(userpassword)
        except self.Expired:
            return ["expired", user]
        else:
            return ["ok", user]



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

