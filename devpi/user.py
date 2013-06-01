import os
import sys
import py
import json

from devpi import log
from devpi.config import getconfig, parse_keyvalue_spec

def getnewpass(hub, username):
    for i in range(3):
        basemessage = "new password for user %s:" %(username)
        password = py.std.getpass.getpass(basemessage)
        password2 = py.std.getpass.getpass("repeat " + basemessage)
        if password == password2:
            return password
        hub.error("passwords did not match")

def create_user(hub, user, email):
    req = dict(user=user, email=email)
    req["password"] = getnewpass(hub, user)
    r = hub.http.put(hub.config.getuserurl(user), json.dumps(req))
    if r.status_code == 200:
        hub.info("created user %r" % user)
    else:
        hub.error("failed to create user %r, server returned %s: %s" %(
                  user, r.status_code, r.reason))
        return 1


def useradd(hub, args):
    return create_user(hub, args.username, args.email)
