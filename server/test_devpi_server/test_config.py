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
    def test_parse_secret(self, caplog, tmpdir):
        # create a secret file
        configdir = tmpdir.ensure_dir('config')
        configdir.chmod(0o700)
        p = configdir.join("secret")
        secret = b"qwoieuqwelkj1234qwoieuqwelkj1234"
        p.write(secret)
        p.chmod(0o600)
        # and use it
        caplog.clear()
        config = make_config(["devpi-server", "--secretfile=%s" % p])
        assert config.args.secretfile == str(p)
        assert config.secretfile == str(p)
        assert config.basesecret == secret
        recs = caplog.getrecords(".*new random secret.*")
        assert len(recs) == 0
        # now check the default
        caplog.clear()
        config = make_config(["devpi-server", "--serverdir", configdir.strpath])
        assert config.args.secretfile is None
        assert config.secretfile is None
        assert config.basesecret != secret
        recs = caplog.getrecords(".*new random secret.*")
        assert len(recs) == 1
        # remember the secret
        prev_secret = config.basesecret
        # each startup without a secret file creates a new random secret
        caplog.clear()
        config = make_config(["devpi-server", "--serverdir", configdir.strpath])
        assert config.args.secretfile is None
        assert config.secretfile is None
        assert config.basesecret != secret
        assert config.basesecret != prev_secret
        recs = caplog.getrecords(".*new random secret.*")
        assert len(recs) == 1

    def test_bbb_default_secretfile_location(self, caplog, recwarn, tmpdir):
        import warnings
        warnings.simplefilter("always")
        # setup secret file in old default location
        configdir = tmpdir.ensure_dir('config')
        configdir.chmod(0o700)
        p = configdir.join(".secret")
        secret = b"qwoieuqwelkj1234qwoieuqwelkj1234"
        p.write(secret)
        p.chmod(0o600)
        caplog.clear()
        config = make_config(["devpi-server", "--serverdir", configdir.strpath])
        # the existing file should be used
        assert config.args.secretfile is None
        assert config.secretfile == str(p)
        assert config.basesecret == secret
        recs = caplog.getrecords(".*new random secret.*")
        assert len(recs) == 0
        assert len(recwarn) == 1
        warning = recwarn.pop(Warning)
        assert 'deprecated existing secret' in warning.message.args[0]

    def test_secret_complexity(self, tmpdir):
        # create a secret file with too short secret
        configdir = tmpdir.ensure_dir('config')
        configdir.chmod(0o700)
        p = configdir.join("secret")
        secret = b"qwoieuqwelkj123"
        p.write(secret)
        p.chmod(0o600)
        # and use it
        config = make_config(["devpi-server", "--secretfile=%s" % p])
        with pytest.raises(Fatal, match="at least 32 characters"):
            config.basesecret
        # create a secret file which is too repetitive
        p = configdir.join("secret")
        secret = b"12345" * 7
        p.write(secret)
        p.chmod(0o600)
        # and use it
        config = make_config(["devpi-server", "--secretfile=%s" % p])
        with pytest.raises(Fatal, match="less repetition"):
            config.basesecret

    @pytest.mark.skipif("sys.platform == 'win32'")
    def test_secretfile_permissions(self, tmpdir):
        # create a secret file with too short secret
        configdir = tmpdir.ensure_dir('config')
        configdir.chmod(0o777)
        p = configdir.join("secret")
        secret = b"qwoieuqwelkj123"
        p.write(secret)
        p.chmod(0o677)
        config = make_config(["devpi-server", "--secretfile=%s" % p])
        with pytest.raises(Fatal, match="file is world accessible"):
            config.basesecret
        p.chmod(0o670)
        with pytest.raises(Fatal, match="file is group accessible"):
            config.basesecret
        p.chmod(0o600)
        with pytest.raises(Fatal, match="folder of the given secret file is group writable"):
            config.basesecret
        configdir.chmod(0o707)
        with pytest.raises(Fatal, match="folder of the given secret file is world writable"):
            config.basesecret

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
        with pytest.raises(Fatal, match="need to specify --master-url"):
            config.init_nodeinfo()

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

    @pytest.mark.parametrize('opts, expected', [
        # defaults
        ((), dict(host='localhost', port=3141)),
        # host/port
        (('--host', 'foo'), dict(host='foo', port=3141)),
        (('--port', '1234'), dict(host='localhost', port=1234)),
        (('--host', 'foo', '--port', '1234'), dict(host='foo', port=1234)),
        # listen
        (('--listen', '*:3141'), dict(listen='*:3141')),
        (('--listen', '127.0.0.1:3141'), dict(listen='127.0.0.1:3141')),
        (('--listen', '[::1]:3141'), dict(listen='[::1]:3141')),
        (('--listen', '127.0.0.1:3141', '--listen', '[::1]:3142'), dict(listen='127.0.0.1:3141 [::1]:3142')),
        (('--host', 'foo', '--listen', '127.0.0.1:3141'), Fatal('You can use either --listen or --host/--port, not both together.')),
        (('--port', '1234', '--listen', '127.0.0.1:3141'), Fatal('You can use either --listen or --host/--port, not both together.')),
        (('--host', 'foo', '--port', '1234', '--listen', '127.0.0.1:3141'), Fatal('You can use either --listen or --host/--port, not both together.')),
    ])
    def test_waitress_info_listen_host_port(self, expected, opts):
        config = make_config(("devpi-server",) + opts)
        try:
            result = {
                k: v
                for k, v in config.waitress_info['kwargs'].items()
                if k in ('host', 'port', 'listen')}
        except Exception as e:
            if not isinstance(e, expected.__class__):
                raise
            assert e.args == expected.args
        else:
            assert result == expected

    def test_waitress_info_trusted_proxy(self):
        config = make_config((
            "devpi-server",
            "--trusted-proxy", "127.0.0.1",
            "--trusted-proxy-count", "2",
            "--trusted-proxy-headers", "x-forwarded-for x-forwarded-host x-forwarded-proto x-forwarded-port"))
        kwargs = config.waitress_info['kwargs']
        assert kwargs["trusted_proxy"] == "127.0.0.1"
        assert kwargs["trusted_proxy_count"] == 2
        assert kwargs["trusted_proxy_headers"] == "x-forwarded-for x-forwarded-host x-forwarded-proto x-forwarded-port"


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

    def test_requests_only(self, make_yaml_config):
        yaml_path = make_yaml_config(textwrap.dedent("""\
            devpi-server:
              requests-only: false"""))
        config = make_config(["devpi-server", "-c", yaml_path])
        assert config.args.requests_only is False
        yaml_path = make_yaml_config(textwrap.dedent("""\
            devpi-server:
              requests-only: true"""))
        config = make_config(["devpi-server", "-c", yaml_path])
        assert config.args.requests_only is True

    @pytest.mark.no_storage_option
    def test_storage_backend_options(self, makexom, make_yaml_config):
        class Plugin:
            @hookimpl
            def devpiserver_storage_backend(self, settings):
                from devpi_server import keyfs_sqlite_fs
                self.settings = settings
                return dict(
                    storage=keyfs_sqlite_fs.Storage,
                    name="foo",
                    description="Foo backend")
        yaml_path = make_yaml_config(textwrap.dedent("""\
            devpi-server:
              storage:
                name: foo
                bar: ham"""))
        options = ("-c", yaml_path)
        config = make_config(("devpi-server",) + options)
        assert isinstance(config.args.storage, dict)
        plugin = Plugin()
        xom = makexom(plugins=(plugin,), opts=options)
        assert xom.config.storage_info["name"] == "foo"
        assert plugin.settings == {"bar": "ham"}
