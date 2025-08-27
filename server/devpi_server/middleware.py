from urllib.parse import urlparse


class OutsideURLMiddleware:
    def __init__(self, app, xom):
        self.app = app
        self.xom = xom

    def __call__(self, environ, start_response):
        outside_url = environ.get('HTTP_X_OUTSIDE_URL')
        if not outside_url:
            outside_url = self.xom.config.outside_url
        if outside_url:
            outside_url = urlparse(outside_url)
            environ['wsgi.url_scheme'] = outside_url.scheme
            environ['HTTP_HOST'] = outside_url.netloc
            if outside_url.path:
                environ['SCRIPT_NAME'] = outside_url.path
                environ["PATH_INFO"] = environ["PATH_INFO"].removeprefix(
                    outside_url.path
                )
        return self.app(environ, start_response)
