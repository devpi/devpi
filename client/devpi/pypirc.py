"""
helpers for authenticating against info from .pypirc files.
"""
import py

class Auth:
    def __init__(self, path=None):
        if path is None:
            path = py.path.local._gethomedir().join(".pypirc")
        self.path = path
        self.ini = py.iniconfig.IniConfig(path)

    def validate_user(self, url, user, password):
        indexservers = self.ini.get("distutils", "index-servers")
        assert indexservers, "no index-servers entry found in %s" % (self.path,)
        url = url.rstrip("/")
        for indexserver in indexservers.split():
            section = self.ini[indexserver]
            repo = section.get("repository")
            repo = repo.rstrip("/")
            if repo == url:
                if user == section["username"] and \
                   password == section["password"]:
                    return True
        print ("auth failed", url, user, password)

    def get_userpass(self, url):
        indexservers = self.ini.get("distutils", "index-servers")
        assert indexservers, "no index-servers entry found in %s" % (self.path,)
        url = url.rstrip("/")
        for indexserver in indexservers.split():
            section = self.ini[indexserver]
            repo = section.get("repository")
            if repo and repo.rstrip("/") == url:
                return (section["username"], section["password"])
        return None

    def get_url_auth(self, secname):
        section = self.ini[secname]
        repo = section.get("repository")
        auth = (section["username"], section["password"])
        return repo, auth


