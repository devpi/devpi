from devpi.main import hookimpl
import getpass


def main(hub, args):
    if not hub.current.root_url:
        hub.fatal("not connected to a server, see 'devpi use'")
    user = args.username
    if user is None:
        user = hub.raw_input("user: ")
    password = args.password
    if password is None:
        password = hub.hook.devpiclient_get_password(
            url=hub.current.root_url.url, username=user)
    input = dict(user=user, password=password)
    r = hub.http_api("post", hub.current.login, input, quiet=False)
    hub.current.set_auth(user, r.result["password"])
    hours = r.result["expiration"] / (60*60.0)
    msg = "logged in %r" % user
    if hub.current.index:
        msg = "%s at %r" % (msg, hub.current.index)
    msg = "%s, credentials valid for %.2f hours" % (msg, hours)
    hub.info(msg)


@hookimpl(trylast=True)
def devpiclient_get_password(url, username):
    return getpass.getpass("password for user %s at %s: " % (username, url))


def logoff(hub, args):
    if hub.current.get_auth():
        hub.current.del_auth()
        hub.info("login information deleted")
    else:
        hub.error("not logged in")
