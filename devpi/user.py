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

def user_create(hub, user, email, password):
    req = dict(user=user, email=email, password=password)
    if password is None:
        req["password"] = getnewpass(hub, user)
    r = hub.http.put(hub.config.getuserurl(user), json.dumps(req))
    if r.status_code == 201:
        hub.info("created user %r" % user)
    else:
        hub.error("failed to create user %r, server returned %s: %s" %(
                  user, r.status_code, r.reason))
        return 1

def user_modify(hub, user, email, password):
    req = dict(user=user)
    if email is not None:
        req["email"] = email
    if password is not None:
        req["password"] = password
    r = hub.http.patch(hub.config.getuserurl(user), json.dumps(req))
    if r.status_code == 200:
        hub.info("modified user %r" % user)
    else:
        hub.error("failed to modify user %r, server returned %s: %s" %(
                  user, r.status_code, r.reason))
        return 1

def user_delete(hub, user):
    r = hub.http.delete(hub.config.getuserurl(user))
    if r.status_code == 200:
        hub.info("deleted user %r" % user)
    else:
        hub.error("failed to delete user %r, server returned %s: %s" %(
                  user, r.status_code, r.reason))
        return 1

def user_list(hub):
    r = hub.http.get(hub.config.rooturl)
    if r.status_code == 200:
        hub.info("list of users")
        data = r.json()
        for user in sorted(data):
            hub.line("%s/" % (user,))
            userconfig = data[user]
            indexes = userconfig.get("indexes")
            if indexes:
                for index in sorted(indexes):
                    indexconfig = indexes[index]
                    hub.line("  %s: %s bases=%s  volatile=%s" %(
                             index, indexconfig["type"],
                             indexconfig["bases"],
                             indexconfig["volatile"]))
    else:
        hub.error("failed to get list of users, server returned %s: %s" %(
                  r.status_code, r.reason))
        return 1

def main(hub, args):
    username = args.username
    password = args.password
    email = args.email
    if args.create:
        return user_create(hub, username, email, password)
    if args.delete:
        return user_delete(hub, username)
    if args.modify:
        return user_modify(hub, username, email, password)
    if args.list:
        return user_list(hub)
