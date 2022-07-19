import pytest
import json
import textwrap
from devpi.main import Hub
from devpi.push import parse_target, PyPIPush, DevpiPush
from subprocess import check_output


def runproc(cmd):
    args = cmd.split()
    return check_output(args)


def test_parse_target_devpi(loghub):
    class args:
        target = "user/name"
        index = None
    res = parse_target(loghub, args)
    assert isinstance(res, DevpiPush)


def test_parse_target_pypi(tmpdir, loghub):
    p = tmpdir.join("pypirc")
    p.write(textwrap.dedent("""
        [distutils]
        index-servers = whatever

        [whatever]
        repository: http://anotherserver
        username: test
        password: testp
    """))

    class args:
        target = "pypi:whatever"
        pypirc = str(p)
        index = None

    res = parse_target(loghub, args)
    assert isinstance(res, PyPIPush)
    assert res.user == "test"
    assert res.password == "testp"
    assert res.posturl == "http://anotherserver"


def test_parse_target_pypi_default_repository(tmpdir, loghub):
    p = tmpdir.join("pypirc")
    p.write(textwrap.dedent("""
        [distutils]
        index-servers = whatever

        [whatever]
        username: test
        password: testp
    """))

    class args:
        target = "pypi:whatever"
        pypirc = str(p)
        index = None

    res = parse_target(loghub, args)
    assert isinstance(res, PyPIPush)
    assert res.user == "test"
    assert res.password == "testp"
    assert res.posturl == "https://upload.pypi.org/legacy/"


def test_push_devpi(loghub, monkeypatch, mock_http_api):
    class args:
        target = "user/name"
        index = None
    pusher = parse_target(loghub, args)
    mock_http_api.set(loghub.current.index, 200, result={})
    pusher.execute(loghub, "pytest", "2.3.5")
    dict(name="pytest", version="2.3.5", targetindex="user/name")
    assert len(mock_http_api.called) == 1
    # loghub.http_api.assert_called_once_with(
    #            "push", loghub.current.index, kvdict=req)


def test_push_devpi_index_option(loghub, monkeypatch, mock_http_api):
    class args:
        target = "user/name"
        index = "src/dev"
    pusher = parse_target(loghub, args)
    mock_http_api.set("src/dev", 200, result={})
    pusher.execute(loghub, "pytest", "2.3.5")
    dict(name="pytest", version="2.3.5", targetindex="user/name")
    assert len(mock_http_api.called) == 1


@pytest.mark.parametrize("spec", ("pkg==1.0", "pkg-1.0"))
def test_main_push_pypi(capsys, monkeypatch, tmpdir, spec):
    from devpi.push import main
    l = []

    def mypost(method, url, data, headers, auth=None, cert=None, verify=None):
        l.append((method, url, data))

        class r:
            status_code = 201
            reason = "created"
            content = json.dumps(dict(type="actionlog", status=201,
                result=[("200", "register", "pkg", "1.0"),
                        ("200", "upload", "pkg-1.3.tar.gz")]
            ))
            headers = {"content-type": "application/json"}
            _json = json.loads(content)
        r.url = url
        return r

    class args:
        clientdir = tmpdir.join("client")
        debug = False
        index = None
    hub = Hub(args)
    monkeypatch.setattr(hub.http, "request", mypost)
    hub.current.reconfigure(dict(index="/some/index"))
    p = tmpdir.join("pypirc")
    p.write(textwrap.dedent("""
        [distutils]
        index-servers = whatever

        [whatever]
        repository: http://anotherserver
        username: test
        password: testp
    """))

    class args:
        pypirc = str(p)
        target = "pypi:whatever"
        pkgspec = spec
        index = None

    main(hub, args)
    assert len(l) == 1
    method, url, data = l[0]
    assert url == hub.current.index
    req = json.loads(data)
    assert req["name"] == "pkg"
    assert req["version"] == "1.0"
    assert req["posturl"] == "http://anotherserver"
    assert req["username"] == "test"
    assert req["password"] == "testp"

    class args:
        pypirc = str(p)
        target = "pypi:notspecified"
        pkgspec = spec
        index = None

    (out, err) = capsys.readouterr()
    with pytest.raises(SystemExit):
        main(hub, args)
    (out, err) = capsys.readouterr()
    assert "Error while trying to read section 'notspecified'" in out
    assert "KeyError" in out


def test_fail_push(monkeypatch, tmpdir):
    from devpi.push import main
    l = []

    def mypost(method, url, data, headers, auth=None, cert=None, verify=None):
        l.append((method, url, data))

        class r:
            status_code = 500
            reason = "Internal Server Error"
            content = json.dumps(dict(type="actionlog", status=201,
                result=[("500", "Internal Server Error", "Internal Server Error")]
            ))
            headers = {"content-type": "application/json"}
            _json = json.loads(content)

            class request:
                method = ''

        r.url = url
        r.request.method = method

        return r

    class args:
        clientdir = tmpdir.join("client")
        debug = False
        index = None
    hub = Hub(args)
    monkeypatch.setattr(hub.http, "request", mypost)
    hub.current.reconfigure(dict(index="/some/index"))
    p = tmpdir.join("pypirc")
    p.write(textwrap.dedent("""
        [distutils]
        index-servers = whatever

        [whatever]
        repository: http://anotherserver
        username: test
        password: testp
    """))

    class args:
        pypirc = str(p)
        target = "pypi:whatever"
        pkgspec = "pkg==1.0"
        index = None

    try:
        main(hub, args)
    except SystemExit as e:
        assert e.code==1


def test_derive_token_non_token():
    class MockHub:
        pass
    hub = MockHub()
    hub.derive_token = Hub.derive_token.__get__(hub)
    assert hub.derive_token("foo", None) == "foo"


@pytest.mark.skipif("sys.version_info >= (3, 6)")
@pytest.mark.parametrize("prefix", ["devpi", "pypi"])
def test_derive_token_old_python(prefix):
    class MockHub:
        pass
    hub = MockHub()
    hub.derive_token = Hub.derive_token.__get__(hub)
    assert hub.derive_token("%s-foo" % prefix, None) == "%s-foo" % prefix


@pytest.mark.skipif("sys.version_info < (3, 6)")
@pytest.mark.parametrize("prefix", ["devpi", "pypi"])
def test_derive_token_invalid_token(prefix):
    msgs = []

    class MockHub:
        def warn(self, msg):
            msgs.append(msg)
    hub = MockHub()
    hub.derive_token = Hub.derive_token.__get__(hub)
    hub.derive_token("%s-foo" % prefix, None) == "%s-foo" % prefix
    (msg,) = msgs
    assert "can not parse it" in msg


@pytest.mark.skipif("sys.version_info < (3, 6)")
def test_derive_token():
    import pypitoken.token
    token = pypitoken.token.Token.create(
        domain="example.com",
        identifier="devpi",
        key="secret")
    passwd = token.dump()
    msgs = []

    class MockHub:
        def info(self, msg):
            msgs.append(msg)
    hub = MockHub()
    hub.derive_token = Hub.derive_token.__get__(hub)
    derived_passwd = hub.derive_token(passwd, 'pkg', now=10)
    assert derived_passwd != passwd
    (msg,) = msgs
    assert "created a unique PyPI token" in msg
    derived_token = pypitoken.token.Token.load(derived_passwd)
    assert derived_token.restrictions == [
        pypitoken.token.ProjectsRestriction(projects=["pkg"]),
        pypitoken.token.DateRestriction(not_before=9, not_after=70)]


@pytest.mark.skipif("sys.version_info < (3, 6)")
def test_derive_devpi_token():
    import pypitoken
    passwd = "devpi-AgEAAhFmc2NodWx6ZS1yTlk5a0RuYQAABiBcjsOFkn7_3fn6mFoeJve_cOv-thDRL-4fQzbf_sOGjQ"
    msgs = []

    class MockHub:
        def info(self, msg):
            msgs.append(msg)
    hub = MockHub()
    hub.derive_token = Hub.derive_token.__get__(hub)
    derived_passwd = hub.derive_token(passwd, 'pkg', now=10)
    assert derived_passwd != passwd
    (msg,) = msgs
    assert "created a unique Devpi token" in msg
    derived_token = pypitoken.token.Token.load(derived_passwd)
    assert derived_token.restrictions == [
        pypitoken.token.ProjectsRestriction(projects=["pkg"]),
        pypitoken.token.DateRestriction(not_before=9, not_after=70)]


class TestPush:
    def test_help(self, ext_devpi):
        result = ext_devpi("push", "-h")
        assert result.ret == 0
        result.stdout.fnmatch_lines("""
            *TARGET*
        """)
