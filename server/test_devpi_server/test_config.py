from devpi_server.config import MyArgumentParser, parseoptions, get_pluginmanager
from devpi_server.config import hookimpl
from devpi_server.main import Fatal
import pytest
import textwrap


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
        parser.post_process_actions()
        assert "[world]" in opt.help

    def test_addoption_getdefault(self):
        def getter(name):
            return dict(hello="world2")[name]
        parser = MyArgumentParser()
        opt = parser.addoption("--hello", default="world", type=str, help="x")
        parser.post_process_actions(defaultget=getter)
        assert opt.default == "world2"
        assert "[world2]" in opt.help
        opt = parser.addoption("--hello2", default="world", type=str, help="x")
        parser.post_process_actions(defaultget=getter)
        assert opt.default == "world"
        assert "[world]" in opt.help

    def test_addgroup(self):
        parser = MyArgumentParser()
        group = parser.addgroup("hello")
        opt = group.addoption("--hello", default="world", type=str, help="x")
        parser.post_process_actions()
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
        config = make_config(["devpi-server", "--serverdir", tmpdir.strpath])
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
        monkeypatch.setenv("DEVPI_SERVERDIR", tmpdir.strpath)
        config = make_config(["devpi-server"])
        assert config.serverdir == tmpdir

    def test_devpiserver_serverdir_env(self, tmpdir, monkeypatch):
        monkeypatch.setenv("DEVPISERVER_SERVERDIR", tmpdir.strpath)
        config = make_config(["devpi-server"])
        assert config.serverdir == tmpdir

    def test_role_permanence_standalone(self, tmpdir):
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "standalone"
        config = make_config(["devpi-server", "--role=standalone",
                               "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "standalone"
        with pytest.raises(Fatal):
            make_config(["devpi-server", "--role=replica",
                          "--serverdir", str(tmpdir)]).init_nodeinfo()
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "standalone"

    def test_role_permanence_master(self, tmpdir):
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "standalone"
        config = make_config(["devpi-server", "--role=master",
                               "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "master"
        with pytest.raises(Fatal):
            make_config(["devpi-server", "--role=replica",
                          "--serverdir", str(tmpdir)]).init_nodeinfo()
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "standalone"

    def test_role_permanence_replica(self, tmpdir):
        config = make_config(["devpi-server", "--master-url", "http://qwe",
                               "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "replica"
        assert not config.get_master_uuid()
        config = make_config(["devpi-server", "--serverdir", str(tmpdir)])
        config.init_nodeinfo()
        assert config.role == "replica"
        assert not config.get_master_uuid()
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
            @hookimpl
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
            @hookimpl
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


class TestConfigFile:
    @pytest.fixture(params=(True, False))
    def make_yaml_config(self, request, tmpdir):
        def make_yaml_config(content):
            yaml = tmpdir.join('devpi.yaml')
            if request.param is True:
                content = "---\n" + content
            yaml.write(content)
            return yaml.strpath

        return make_yaml_config

    @pytest.fixture
    def load_yaml_config(self, make_yaml_config):
        from devpi_server.config import load_config_file

        def load_yaml_config(content):
            return load_config_file(make_yaml_config(content))

        return load_yaml_config

    def test_empty(self, load_yaml_config):
        assert load_yaml_config("") == {}

    def test_no_server_section(self, load_yaml_config):
        assert load_yaml_config("devpi-ldap:") == {}

    def test_invalid(self, load_yaml_config):
        from devpi_server.config import InvalidConfigError
        with pytest.raises(InvalidConfigError):
            assert load_yaml_config("- foo") == {}
        with pytest.raises(InvalidConfigError):
            assert load_yaml_config("devpi-server:\n  - foo") == {}

    def test_empty_key(self, load_yaml_config):
        assert load_yaml_config("devpi-server:") == {}

    def test_port(self, make_yaml_config):
        yaml_path = make_yaml_config(textwrap.dedent("""\
            devpi-server:
              port: 3142"""))
        config = make_config(["devpi-server", "-c", yaml_path])
        assert config.args.port == 3142

    def test_invalid_port(self, capsys, make_yaml_config):
        yaml_path = make_yaml_config(textwrap.dedent("""\
            devpi-server:
              port: foo"""))
        with pytest.raises(SystemExit):
            make_config(["devpi-server", "-c", yaml_path])
        (out, err) = capsys.readouterr()
        assert "argument --port: invalid int value: 'foo'" in err
