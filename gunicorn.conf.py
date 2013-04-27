###
# app configuration
# http://docs.pylonsproject.org/projects/pyramid/en/latest/narr/environment.html
###

from devpi_server.wsgi import post_fork

bind = "0.0.0.0:6543"
worker_class = "eventlet"
workers = 1
loglevel = "debug"
preload_app = False
