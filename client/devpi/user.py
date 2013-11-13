import py
from devpi.use import parse_keyvalue_spec

def getnewpass(hub, username):
    for i in range(3):
        basemessage = "new password for user %s:" %(username)
        password = py.std.getpass.getpass(basemessage)
        password2 = py.std.getpass.getpass("repeat " + basemessage)
        if password == password2:
            return password
        hub.error("passwords did not match")

def user_create(hub, user, kvdict):
    if "password" not in kvdict:
        kvdict["password"] = getnewpass(hub, user)
    hub.http_api("put", hub.current.get_user_url(user), kvdict)
    hub.info("user created: %s" % user)

def user_modify(hub, user, kvdict):
    hub.http_api("patch", hub.current.get_user_url(user), kvdict)
    hub.info("user modified: %s" % user)

def user_delete(hub, user):
    hub.http_api("delete", hub.current.get_user_url(user), None)
    hub.info("user deleted: %s" % user)

def user_list(hub):
    r = hub.http_api("get", hub.current.rooturl)
    for name in r.result or []:
        hub.line(name)

def main(hub, args):
    username = args.username
    if not args.list and not username:
        hub.fatal("need to specify a username")
    kvdict = parse_keyvalue_spec(args.keyvalues)
    if args.create:
        return user_create(hub, username, kvdict)
    elif args.delete:
        return user_delete(hub, username)
    elif args.modify:
        return user_modify(hub, username, kvdict)
    elif args.list:
        return user_list(hub)
    else:
        hub.fatal("need to specify -c|-d|-m|-l")
