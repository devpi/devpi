from devpi_server.config import MyArgumentParser, parseoptions, get_pluginmanager
from devpi_server.main import Fatal
import pytest

def make_config(args):
    return parseoptions(get_pluginmanager(), args)


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
        config = make_config(["devpi-server", "--secretfile=%s" % p])
        assert config.secretfile == str(p)
        assert config.secret == secret
        config = make_config(["devpi-server", "--serverdir", tmpdir])
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
        config = make_config(["devpi-server"])
        assert config.serverdir == tmpdir

    def test_role_permanence_master(self, tmpdir):
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "master"
        config = make_config(["devpi-server", "--role=master",
                               "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "master"
        with pytest.raises(Fatal):
            make_config(["devpi-server", "--role=replica",
                          "--serverdir", str(tmpdir)]).init_nodeinfo()

    def test_role_permanence_replica(self, tmpdir):
        config = make_config(["devpi-server", "--master-url", "http://qwe",
                               "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "replica"
        assert not config.get_master_uuid()
        with pytest.raises(Fatal) as excinfo:
            make_config(["devpi-server", "--serverdir", str(tmpdir)]).init_nodeinfo()
        assert "specify --role=master" in str(excinfo.value)
        config = make_config(["devpi-server", "--serverdir", str(tmpdir),
                               "--role=master"])
        config.init_nodeinfo()
        assert config.role == "master"
        with pytest.raises(Fatal):
            make_config(["devpi-server", "--master-url=xyz",
                          "--serverdir", str(tmpdir)]).init_nodeinfo()
        with pytest.raises(Fatal):
            make_config(["devpi-server", "--role=replica",
                          "--serverdir", str(tmpdir)]).init_nodeinfo()

    def test_replica_role_missing_master_url(self, tmpdir):
        config = make_config(["devpi-server", "--role=replica",
                             "--serverdir", str(tmpdir)])
        with pytest.raises(Fatal) as excinfo:
            config.init_nodeinfo()
        assert "need to specify --master-url" in str(excinfo)

    def test_uuid(self, tmpdir):
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        uuid = config.nodeinfo["uuid"]
        assert uuid
        assert config.get_master_uuid() == uuid
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        assert uuid == config.nodeinfo["uuid"]
        tmpdir.remove()
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.nodeinfo["uuid"] != uuid
        assert config.get_master_uuid() != uuid

    def test_add_parser_options_called(self):
        l = []
        class Plugin:
            def devpiserver_add_parser_options(self, parser):
                l.append(parser)
        pm = get_pluginmanager()
        pm.register(Plugin())
        parseoptions(pm, ["devpi-server"])
        assert len(l) == 1
        assert isinstance(l[0], MyArgumentParser)

    def test_logger_cfg(self):
        config = make_config(["devpi-server"])
        assert not config.args.logger_cfg
        config_file = 'path/to/a.file'
        config = make_config(["devpi-server", "--logger-cfg", config_file])
        assert config.args.logger_cfg == config_file

    def test_keyfs_cache_size(self, makexom):
        opts = ("--keyfs-cache-size", "200")
        config = make_config(("devpi-server",) + opts)
        assert config.args.keyfs_cache_size == 200
        xom = makexom(opts=opts)
        assert xom.keyfs._storage._changelog_cache.size == 200

    @pytest.mark.no_storage_option
    def test_storage_backend_default(self, makexom):
        from devpi_server import keyfs_sqlite
        from devpi_server import keyfs_sqlite_fs
        config = make_config(("devpi-server",))
        assert config.args.storage is None
        xom = makexom(plugins=(keyfs_sqlite, keyfs_sqlite_fs))
        assert xom.config.storage is keyfs_sqlite_fs.Storage

    def test_storage_backend_persisted(self, tmpdir):
        from devpi_server import keyfs_sqlite
        config = make_config(["devpi-server",
                              "--serverdir", str(tmpdir),
                              "--storage", "sqlite_db_files"])
        config.init_nodeinfo()
        assert config.storage is keyfs_sqlite.Storage
        config = make_config(["devpi-server",
                              "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.storage is keyfs_sqlite.Storage
        config = make_config(["devpi-server",
                              "--serverdir", str(tmpdir),
                              "--storage", "sqlite"])
        with pytest.raises(Fatal):
            config.init_nodeinfo()

    @pytest.mark.no_storage_option
    def test_storage_backend_options(self, makexom):
        class Plugin:
            def devpiserver_storage_backend(self, settings):
                from devpi_server import keyfs_sqlite_fs
                self.settings = settings
                return dict(
                    storage=keyfs_sqlite_fs.Storage,
                    name="foo",
                    description="Foo backend")
        options = ("--storage", "foo:bar=ham")
        config = make_config(("devpi-server",) + options)
        assert config.args.storage == "foo:bar=ham"
        plugin = Plugin()
        makexom(plugins=(plugin,), opts=options)
        assert plugin.settings == {"bar": "ham"}
