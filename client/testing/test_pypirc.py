
from devpi import pypirc
from textwrap import dedent

def test_pypirc(tmpdir):
    p = tmpdir.join("pypirc")
    p.write(dedent("""\n
        [distutils]
        index-servers = local
            testindex

        [local]
        repository: http://pypi.testrun.org/
        username: test
        password: test

        [testindex]
        repository: http://localhost:3141/
        username: test2
        password: test2
    """))
    rc = pypirc.Auth(p)
    assert rc.validate_user("http://pypi.testrun.org/", "test", "test")
    assert not rc.validate_user("http://pypi.testrun.org/", "test", "test2")
    assert rc.validate_user("http://localhost:3141/", "test2", "test2")
    assert not rc.validate_user("http://localhost:3141/", "test", "test")

    userpass = rc.get_userpass("http://pypi.testrun.org/")
    assert userpass == ("test", "test")
    userpass = rc.get_userpass("http://localhost:3141/")
    assert userpass == ("test2", "test2")
    userpass = rc.get_userpass("http://qwleklocalhost:3141/")
    assert userpass is None

    url, (user, p) = rc.get_url_auth("local")
    assert url == "http://pypi.testrun.org/"
    assert user == "test"
    assert p == "test"
