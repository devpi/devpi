from devpi.use import get_keyvalues
import getpass


def getnewpass(hub, username):
    for i in range(3):
        basemessage = "new password for user %s:" %(username)
        password = getpass.getpass(basemessage)
        password2 = getpass.getpass("repeat " + basemessage)
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
    if "password" not in kvdict and "pwhash" not in kvdict:
        kvdict["password"] = getnewpass(hub, user)
    hub.http_api("put", hub.current.get_user_url(user), kvdict)
    hub.info("user created: %s" % user)

def user_modify(hub, user, kvdict):
    url = hub.current.get_user_url(user)
    reply = hub.http_api("get", url, type="userconfig")
    for name, val in kvdict.items():
        reply.result[name] = val
        if name == 'password':
            # hide password from log output
            val = '********'
        hub.info("%s changing %s: %s" %(url.path, name, val))

    for name in ('indexes', 'username'):
        # pre devpi-server 3.0.0 can't handle these
        reply.result.pop(name, None)

    hub.http_api("patch", url, reply.result)
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
    kvdict = get_keyvalues(args.keyvalues).kvdict
    if args.create:
        return user_create(hub, username, kvdict)
    elif args.delete:
        return user_delete(hub, username)
    elif kvdict or args.modify:
        return user_modify(hub, username, kvdict)
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
    user_modify(hub, user, dict(password=getnewpass(hub, user)))
