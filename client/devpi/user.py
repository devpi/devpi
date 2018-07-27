import py
from devpi.use import KeyValueOperations, parse_keyvalue_spec
from devpi.use import json_patch_from_keyvalues


def getnewpass(hub, username):
    for i in range(3):
        basemessage = "new password for user %s:" %(username)
        password = py.std.getpass.getpass(basemessage)
        password2 = py.std.getpass.getpass("repeat " + basemessage)
        if password == password2:
            if not password:
                if not hub.ask_confirm("empty password, are you sure to use it?"):
                    continue
            elif len(password) < 8:
                if not hub.ask_confirm("password with less than 8 characters, are you sure to use it?"):
                    continue
            return password
        hub.error("passwords did not match")

def user_create(hub, user, kvdict):
    if "password" not in kvdict:
        kvdict["password"] = getnewpass(hub, user)
    hub.http_api("put", hub.current.get_user_url(user), kvdict)
    hub.info("user created: %s" % user)


def user_modify(hub, user, keyvalues):
    url = hub.current.get_user_url(user)
    features = hub.current.features or set()
    reply = hub.http_api("get", url, type="userconfig")
    if 'server-jsonpatch' in features:
        # the server supports JSON patch
        try:
            patch = json_patch_from_keyvalues(keyvalues, reply.result)
        except ValueError as e:
            hub.fatal(e)
        for op in patch:
            value = op['value']
            if op['path'] == '/password':
                # hide password from log output
                value = '********'
            hub.info("%s %s %s %s" % (url.path, op['op'], op['path'], value))
    else:
        try:
            kvdict = keyvalues.kvdict
        except ValueError as e:
            hub.fatal(e)
        patch = reply.result
        for name, val in kvdict.items():
            patch[name] = val
            if name == 'password':
                # hide password from log output
                val = '********'
            hub.info("%s changing %s: %s" %(url.path, name, val))

        for name in ('indexes', 'username'):
            # pre devpi-server 3.0.0 can't handle these
            patch.pop(name, None)

    hub.http_api("patch", url, patch)
    hub.info("user modified: %s" % user)

def user_delete(hub, user):
    url = hub.current.get_user_url(user)
    hub.info("About to remove: %s" % url)
    if hub.ask_confirm("Are you sure"):
        hub.http_api("delete", url, None)
        hub.info("user deleted: %s" % user)

def user_list(hub):
    r = hub.http_api("get", hub.current.rooturl)
    for name in r.result or []:
        hub.line(name)


def user_show(hub, user):
    if not user:
        user = hub.current.get_auth_user()
    if not user:
        hub.fatal("no user specified and no user currently active")
    url = hub.current.get_user_url(user)
    reply = hub.http_api("get", url, quiet=True, type="userconfig")
    userconfig = reply.result
    hub.info(url.url + ":")
    skip = set(('indexes', 'username'))
    for key, value in sorted(userconfig.items()):
        if key in skip:
            continue
        if isinstance(value, list):
            value = ",".join(value)
        hub.line("  %s=%s" % (key, value))


def main(hub, args):
    username = args.username
    if (args.delete or args.create) and not username:
        hub.fatal("need to specify a username")
    keyvalues = parse_keyvalue_spec(args.keyvalues)
    if args.create:
        return user_create(hub, username, keyvalues.kvdict)
    elif args.delete:
        return user_delete(hub, username)
    elif keyvalues or args.modify:
        return user_modify(hub, username, keyvalues)
    elif args.list:
        return user_list(hub)
    else:
        return user_show(hub, username)


def passwd(hub, args):
    user = args.username
    if not user:
        user = hub.current.get_auth_user()
    if not user:
        hub.fatal("no user specified and no user currently active")
    user_modify(hub, user, KeyValueOperations([
        ("default", "password", getnewpass(hub, user))]))
