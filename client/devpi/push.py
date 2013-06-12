import py
from devpi import log
from devpi.util import version as verlib
from devpi.util import pypirc

def main(hub, args):
    pypirc_path = args.pypirc
    if pypirc_path is None:
        pypirc_path = py.path.local._gethomedir().join(".pypirc")
    else:
        pypirc_path = py.path.local().join(args.pypirc, abs=True)
    assert pypirc_path.check()

    hub.info("using pypirc", pypirc_path)
    auth = pypirc.Auth(pypirc_path)
    posturl, (user, password) = auth.get_url_auth(args.posturl)
    name, version = verlib.guess_pkgname_and_version(args.nameversion)
    req = dict(name=name, version=str(version), posturl=posturl,
               username=user, password=password )
    index = hub.current.index
    res = hub.http_api("push", index, kvdict=req)
    #assert r.status_code == 200, r.content
    hub.info("pushed %s to %s" % (args.nameversion, posturl))
    if res["status"] == 200:
        assert res["type"] == "actionlog"
        for action in res["result"]:
            red = action[0] >= 400
            hub.line(" ".join(map(str, action)), red=red)
