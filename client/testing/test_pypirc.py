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

        [nopassword]
        repository: http://localhost:3141/
        username: test3
    """))
    rc = pypirc.Auth(p)

    url, (user, p) = rc.get_url_auth("local")
    assert url == "http://pypi.testrun.org/"
    assert user == "test"
    assert p == "test"

    url, (user, p) = rc.get_url_auth("testindex")
    assert url == "http://localhost:3141/"
    assert user == "test2"
    assert p == "test2"

    url, (user, p) = rc.get_url_auth("nopassword")
    assert url == "http://localhost:3141/"
    assert user == "test3"
    assert p is None
