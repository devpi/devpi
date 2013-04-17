
from devpi_server.plugin import hookdecl

@hookdecl()
def server_addoptions(parser):
    """ register command line options. """

@hookdecl(firstresult=True)
def server_cmdline_parse(pm, argv):
    """ parse command line options. """

@hookdecl(firstresult=True)
def server_cmdline_main(config):
    """ perform command line main option. """

@hookdecl(firstresult=True)
def server_mainloop(config):
    """ execute main loop and return integer result code. """

@hookdecl(firstresult=True)
def resource_extdb(config):
    """ return ExtDB instance with support for release links. """

@hookdecl(firstresult=True)
def resource_httpcache(config):
    """ return httpcache object for performing cached http lookups. """

@hookdecl(firstresult=True)
def resource_httpget(config):
    """ return non-redirecting httpget function. """

@hookdecl(firstresult=True)
def resource_redis(config):
    """ return connected redis client object. """
