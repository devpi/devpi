class GetPassException(Exception):
    pass


def failing_getpass(msg):
    raise GetPassException()


def test_passwd_no_user(monkeypatch, out_devpi):
    monkeypatch.setattr("getpass.getpass", failing_getpass)
    out_devpi("logoff")
    res = out_devpi("passwd")
    assert not res.errlines
    assert res.outlines == [
        'no user specified and no user currently active',
        '']


def test_passwd_no_username(devpi_username, monkeypatch, out_devpi):
    monkeypatch.setattr("getpass.getpass", lambda msg: "password")
    res = out_devpi("passwd")
    assert not res.errlines
    assert res.outlines == [
        '/%s changing password: ********' % devpi_username,
        'user modified: %s' % devpi_username,
        '']


def test_passwd(devpi_username, monkeypatch, out_devpi):
    monkeypatch.setattr("getpass.getpass", lambda msg: "password")
    res = out_devpi("use")
    res = out_devpi("passwd", devpi_username)
    assert not res.errlines
    assert res.outlines == [
        '/%s changing password: ********' % devpi_username,
        'user modified: %s' % devpi_username,
        '']


def test_passwd_empty(devpi_username, monkeypatch, out_devpi):
    monkeypatch.setattr("getpass.getpass", lambda msg: "")
    res = out_devpi("passwd")
    assert not res.errlines
    assert res.outlines == [
        'empty password, are you sure to use it?: yes',
        '/%s changing password: ********' % devpi_username,
        'user modified: %s' % devpi_username,
        '']


def test_passwd_short(devpi_username, monkeypatch, out_devpi):
    monkeypatch.setattr("getpass.getpass", lambda msg: "foo")
    res = out_devpi("passwd")
    assert not res.errlines
    assert res.outlines == [
        'password with less than 8 characters, are you sure to use it?: yes',
        '/%s changing password: ********' % devpi_username,
        'user modified: %s' % devpi_username,
        '']
