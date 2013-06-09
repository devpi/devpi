
import os
import sys
import py
import json

from devpi import log
from devpi.use import parse_keyvalue_spec


def main(hub, args):
    user = args.username
    if user is None:
        user = hub.raw_input("user: ")
    password = args.password
    if password is None:
        password = py.std.getpass.getpass("password for user %s: " % user)
    r = hub.http.post(hub.current.login,
                      json.dumps({"user": user, "password": password}))
    if r.status_code == 200:
        data = r.json()
        hub.update_auth(user, data["password"])
        hours = data["expiration"] / (60*60.0)
        hub.info("logged in %r, credentials valid for %.2f hours" %
                 (user, hours))
    else:
        hub.error("server refused %r login, code=%s" %(user, r.status_code))
        return 1

