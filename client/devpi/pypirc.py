"""
helpers for authenticating against info from .pypirc files.
"""
from pathlib import Path
import iniconfig


class Auth:
    def __init__(self, path=None):
        if path is None:
            path = Path().home() / ".pypirc"
        self.ini = iniconfig.IniConfig(path)

    def get_url_auth(self, secname):
        section = self.ini[secname]
        repo = section.get("repository")
        username = section["username"]
        password = section.get("password")
        auth = (username, password)
        return repo, auth
