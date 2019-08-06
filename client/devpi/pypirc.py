"""
helpers for authenticating against info from .pypirc files.
"""
import py


class Auth:
    def __init__(self, path=None):
        if path is None:
            path = py.path.local._gethomedir().join(".pypirc")
        self.ini = py.iniconfig.IniConfig(path)

    def get_url_auth(self, secname):
        section = self.ini[secname]
        repo = section.get("repository")
        auth = (section["username"], section["password"])
        return repo, auth
