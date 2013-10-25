import py

def main(hub, args):
    user = args.username
    if user is None:
        user = hub.raw_input("user: ")
    password = args.password
    if password is None:
        password = py.std.getpass.getpass("password for user %s: " % user)
    input = dict(user=user, password=password)
    r = hub.http_api("post", hub.current.login, input, quiet=False)
    hub.current.set_auth(user, r.result["password"])
    hours = r.result["expiration"] / (60*60.0)
    hub.info("logged in %r, credentials valid for %.2f hours" %
             (user, hours))
    #else:
    #    hub.error("server refused %r login, code=%s" %(user, r.status_code))
    #    return 1


def logoff(hub, args):
    if hub.current.get_auth():
        hub.current.del_auth()
        hub.info("login information deleted")
    else:
        hub.error("not logged in")
