from devpi_server.events import EventQueue
from devpi_server.log import threadlog
from urllib.parse import urlparse


class EventIteratorWrapper(object):
    def __init__(self, app_iter, environ, xom):
        self.app_iter = app_iter
        self.environ = environ
        self.xom = xom
        if hasattr(app_iter, 'close'):
            self.close = app_iter.close

    def __iter__(self):
        event_queue = self.environ.pop('devpi.event_queue', None)
        exception = None
        try:
            for data in self.app_iter:
                yield data
        except Exception as e:
            exception = e
        # after data was sent we call the events handler
        try:
            if event_queue is not None:
                event_queue.dispatch(exception=exception)
        except Exception:
            threadlog.exception("Error in EventQueue.handle_context")


class EventMiddleware(object):
    def __init__(self, app, xom):
        self.app = app
        self.xom = xom

    def __call__(self, environ, start_response):
        environ['devpi.event_queue'] = EventQueue(
            context="request",
            keyfs=self.xom.keyfs,
            listeners=self.xom.event_listeners)
        app_iter = self.app(environ, start_response)
        return EventIteratorWrapper(app_iter, environ, self.xom)


class OutsideURLMiddleware(object):
    def __init__(self, app, xom):
        self.app = app
        self.xom = xom

    def __call__(self, environ, start_response):
        outside_url = environ.get('HTTP_X_OUTSIDE_URL')
        if not outside_url:
            outside_url = self.xom.config.args.outside_url
        if outside_url:
            # XXX memoize it for later access from replica thread
            # self.xom.current_outside_url = outside_url
            outside_url = urlparse(outside_url)
            environ['wsgi.url_scheme'] = outside_url.scheme
            environ['HTTP_HOST'] = outside_url.netloc
            if outside_url.path:
                environ['SCRIPT_NAME'] = outside_url.path
        return self.app(environ, start_response)
