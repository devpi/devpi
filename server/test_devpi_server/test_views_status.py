import devpi_server.views
import pytest


pytestmark = [pytest.mark.notransaction]


class TestStatus:
    def test_status_master(self, testapp):
        r = testapp.get_json("/+status", status=200)
        assert r.status_code == 200
        data = r.json["result"]
        assert data["role"] == "MASTER"

    def test_status_replica(self, maketestapp, replica_xom):
        testapp = maketestapp(replica_xom)
        r = testapp.get_json("/+status", status=200)
        assert r.status_code == 200
        data = r.json["result"]
        assert data["role"] == "REPLICA"
        assert data["serial"] == replica_xom.keyfs.get_current_serial()
        assert data["replication-errors"] == {}

    def test_metrics_hook(self, maketestapp, makexom):
        from devpi_server.config import hookimpl

        class Plugin:
            @hookimpl
            def devpiserver_metrics(self):
                return [
                    ('devpi_plugin_my_totals', 'counter', 10.0),
                    ('devpi_plugin_my_size', 'gauge', 20.0)]

        plugin = Plugin()
        xom = makexom(plugins=(plugin,))
        testapp = maketestapp(xom)
        r = testapp.get_json("/+status", status=200)
        assert r.status_code == 200
        data = r.json["result"]
        metrics = []
        for metric in data["metrics"]:
            if metric[0] in ('devpi_plugin_my_size', 'devpi_plugin_my_totals'):
                metrics.append(metric)
        assert sorted(metrics) == [
            ['devpi_plugin_my_size', 'gauge', 20.0],
            ['devpi_plugin_my_totals', 'counter', 10.0]]


class TestStatusInfoPlugin:
    @pytest.fixture
    def plugin(self):
        from devpi_server.views import devpiweb_get_status_info
        return devpiweb_get_status_info

    def _xomrequest(self, xom):
        from pyramid.request import Request
        request = Request.blank("/blankpath")
        request.registry = dict(
            xom=xom,
            devpi_version_info=[])
        return request

    @pytest.mark.with_notifier
    def test_no_issue(self, plugin, xom):
        request = self._xomrequest(xom)
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        # if devpi-web is installed make sure we look again
        # at the serial in case a hook created a new serial
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        result = plugin(request)
        assert not xom.is_replica()
        assert result == []

    @pytest.mark.xfail(reason="sometimes fail due to race condition in db table creation")
    @pytest.mark.with_replica_thread
    @pytest.mark.with_notifier
    def test_no_issue_replica(self, plugin, xom):
        request = self._xomrequest(xom)
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        result = plugin(request)
        assert hasattr(xom, 'replica_thread')
        assert xom.is_replica()
        assert result == []

    def test_events_lagging(self, plugin, xom, monkeypatch):
        # write transaction so event processing can lag behind
        with xom.keyfs.transaction(write=True):
            xom.model.create_user("hello", "pass")

        import time
        now = time.time()
        request = self._xomrequest(xom)
        # nothing if events never processed directly after startup
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 30)
        result = plugin(request)
        assert result == []
        # fatal after 5 minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg="The event processing doesn't seem to start")]
        # fake first event processed
        xom.keyfs.notifier.write_event_serial(0)
        xom.keyfs.notifier.event_serial_in_sync_at = now
        # no report in the first minute
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 30)
        result = plugin(request)
        assert result == []
        # warning after 5 minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='warn',
            msg='No changes processed by plugins for more than 5 minutes')]
        # fatal after 30 minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 1810)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg='No changes processed by plugins for more than 30 minutes')]
        # warning about sync after one hour
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 3610)
        result = plugin(request)
        assert result == [
            dict(
                status='warn',
                msg="The event processing hasn't been in sync for more than 1 hour"),
            dict(
                status='fatal',
                msg='No changes processed by plugins for more than 30 minutes')]
        # fatal sync state after 6 hours
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 21610)
        result = plugin(request)
        assert result == [
            dict(
                status='fatal',
                msg="The event processing hasn't been in sync for more than 6 hours"),
            dict(
                status='fatal',
                msg='No changes processed by plugins for more than 30 minutes')]

    def test_replica_lagging(self, plugin, makexom, monkeypatch):
        import time
        now = time.time()
        xom = makexom(["--master=http://localhost"])
        request = self._xomrequest(xom)
        assert xom.is_replica()
        # fake first serial processed
        xom.replica_thread.update_master_serial(0)
        xom.replica_thread.replica_in_sync_at = now
        # no report in the first minute
        result = plugin(request)
        assert result == []
        # warning after one minute
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 70)
        result = plugin(request)
        assert result == [dict(
            status='warn',
            msg='Replica is behind master for more than 1 minute')]
        # fatal after five minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg='Replica is behind master for more than 5 minutes')]

    def test_initial_master_connection(self, plugin, makexom, monkeypatch):
        import time
        now = time.time()
        xom = makexom(["--master=http://localhost"])
        request = self._xomrequest(xom)
        assert xom.is_replica()
        assert xom.replica_thread.started_at is None
        # fake replica start
        xom.replica_thread.started_at = now
        # no report in the first minute
        result = plugin(request)
        assert result == []
        # warning after one minute
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 70)
        result = plugin(request)
        assert result == [dict(
            status='warn',
            msg='No contact to master for more than 1 minute')]
        # fatal after five minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg='No contact to master for more than 5 minutes')]

    @pytest.mark.xfail(reason="sometimes fail due to race condition in db table creation")
    @pytest.mark.with_replica_thread
    @pytest.mark.with_notifier
    def test_no_master_update(self, plugin, xom, monkeypatch):
        import time
        now = time.time()
        request = self._xomrequest(xom)
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        assert hasattr(xom, 'replica_thread')
        assert xom.is_replica()
        # fake last update
        xom.replica_thread.update_from_master_at = now
        # no report in the first minute
        result = plugin(request)
        assert result == []
        # warning after one minute
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 70)
        result = plugin(request)
        assert result == [dict(
            status='warn',
            msg='No update from master for more than 1 minute')]
        # fatal after five minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg='No update from master for more than 5 minutes')]
