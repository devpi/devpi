import py
from devpi_common.metadata import splitbasename
from . import pypirc

class PyPIPush:
    def __init__(self, posturl, user, password):
        self.posturl = posturl
        self.user = user
        self.password = password

    def execute(self, hub, name, version):
        req = dict(name=name, version=str(version), posturl=self.posturl,
                   username=self.user, password=self.password )
        index = hub.current.index
        return hub.http_api("push", index, kvdict=req, fatal=False)

        #assert r.status_code == 200, r.content

class DevpiPush:
    def __init__(self, targetindex):
        self.targetindex = targetindex

    def execute(self, hub, name, version):
        req = dict(name=name, version=str(version),
                   targetindex=self.targetindex)
        return hub.http_api("push", hub.current.index, kvdict=req, fatal=False)

def parse_target(hub, args):
    if args.target.startswith("pypi:"):
        posturl = args.target[5:]
        pypirc_path = args.pypirc
        if pypirc_path is None:
            pypirc_path = py.path.local._gethomedir().join(".pypirc")
        else:
            pypirc_path = py.path.local().join(args.pypirc, abs=True)
        if not pypirc_path.check():
            hub.fatal("no pypirc file found at: %s" %(pypirc_path))
        hub.info("using pypirc", pypirc_path)
        auth = pypirc.Auth(pypirc_path)
        posturl, (user, password) = auth.get_url_auth(posturl)
        return PyPIPush(posturl, user, password)
    if args.target.count("/") != 1:
        hub.fatal("target %r not of form USER/NAME or pypi:REPONAME" % (
                  args.target, ))
    return DevpiPush(args.target)

def main(hub, args):
    pusher = parse_target(hub, args)
    name, version = splitbasename(args.nameversion + ".zip")[:2]
    r = pusher.execute(hub, name, version)
    if r.type == "actionlog":
        for action in r["result"]:
            red = int(action[0]) >= 400
            for line in (" ".join(map(str, action))).split("\n"):
                hub.line("   " + line, red=red)
