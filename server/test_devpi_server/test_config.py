from devpi_server.config import MyArgumentParser, parseoptions

class TestParser:

    def test_addoption(self):
        parser = MyArgumentParser()
        parser.addoption("--hello", type=str)
        args = parser.parse_args(["--hello", "world"])
        assert args.hello == "world"

    def test_addoption_default_added_to_help(self):
        parser = MyArgumentParser()
        opt = parser.addoption("--hello", type=str, help="x", default="world")
        assert "[world]" in opt.help

    def test_addoption_getdefault(self):
        def getter(name):
            return dict(hello="world2")[name]
        parser = MyArgumentParser(defaultget=getter)
        opt = parser.addoption("--hello", default="world", type=str, help="x")
        assert opt.default == "world2"
        assert "[world2]" in opt.help
        opt = parser.addoption("--hello2", default="world", type=str, help="x")
        assert opt.default == "world"
        assert "[world]" in opt.help

    def test_addgroup(self):
        parser = MyArgumentParser()
        group = parser.addgroup("hello")
        opt = group.addoption("--hello", default="world", type=str, help="x")
        assert opt.default == "world"
        assert "[world]" in opt.help

    def test_addsubparser(self):
        parser = MyArgumentParser()
        sub = parser.add_subparsers()
        p = sub.add_parser("hello")
        assert isinstance(p, MyArgumentParser)

class TestConfig:
    def test_parse_secret(self, tmpdir):
        p = tmpdir.join("secret")
        secret = "qwoieuqwelkj123"
        p.write(secret)
        config = parseoptions(["devpi-server", "--secretfile=%s" % p])
        assert config.secretfile == str(p)
        assert config.secret == secret
        config = parseoptions(["devpi-server", "--serverdir", tmpdir])
        assert config.secretfile == tmpdir.join(".secret")
        config.secretfile.write(secret)
        assert config.secret == config.secretfile.read()

    def test_generated_secret_if_not_exists(self,
                                            xom, tmpdir, monkeypatch):
        config = xom.config
        secfile = tmpdir.join("secret")
        monkeypatch.setattr(config, "secretfile", secfile)
        assert not secfile.check()
        assert config.secret
        assert config.secret == config.secretfile.read()
        assert config.secretfile == secfile
        #recs = caplog.getrecords()

    def test_devpi_serverdir_env(self, tmpdir, monkeypatch):
        monkeypatch.setenv("DEVPI_SERVERDIR", tmpdir)
        config = parseoptions(["devpi-server"])
        assert config.serverdir == tmpdir

