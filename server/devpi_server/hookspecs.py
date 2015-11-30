
from pluggy import HookspecMarker

hookspec = HookspecMarker("devpiserver")


@hookspec
def devpiserver_add_parser_options(parser):
    """ called before command line parsing to allow plugins
    to add options through a call to parser.add_argument().
    """


@hookspec(firstresult=True)
def devpiserver_cmdline_run(xom):
    """ return an integer with a success code (0 == no errors) if
    you handle the command line invocation, otherwise None.  When
    the first plugin returns an integer, the remaining plugins
    are not called."""


@hookspec
def devpiserver_storage_backend(settings):
    """ return dict containing storage backend info.

    The following keys are defined:

        "storage" - the class implementing the storage API
        "name" - name for selection from command line
        "description" - a short description for the commandline help
    """


@hookspec
def devpiserver_pyramid_configure(config, pyramid_config):
    """ called during initializing with the pyramid_config and the devpi_server
    config object. """


@hookspec
def devpiserver_mirror_initialnames(stage, projectnames):
    """ called when projectnames are first loaded into a mirror
    (both for replica and a master)
    """

@hookspec
def devpiserver_stage_created(stage):
    """ called when a stage was successfully created. (both for replica and a master)
    """

@hookspec
def devpiserver_on_changed_versiondata(stage, project, version, metadata):
    """ called when versiondata data changes in a stage for a project/version.
    If metadata is empty the version was deleted. """


@hookspec
def devpiserver_on_upload(stage, project, version, link):
    """ called when a file is uploaded to a private stage for
    a project/version.  link.entry.file_exists() may be false because
    a more recent revision deleted the file (and files are not revisioned).
    NOTE that this hook is currently NOT called for the implicit "caching"
    uploads to the pypi mirror.
    """


@hookspec(firstresult=True)
def devpiserver_get_credentials(request):
    """Extracts username and password from request.

    Returns a tuple with (username, password) if credentials could be
    extracted, or None if no credentials were found.  The first plugin
    to return credentials is used.
    """


@hookspec
def devpiserver_auth_user(userdict, username, password):
    """return dict containing authentication validation results.

    A dict must be returned with a key "status" with one of the
    following values:

        "ok" - authentication succeeded
        "unknown" - no matching user, other plugins are tried
        "reject" - invalid password, authentication stops

    Optionally the plugin can return a list of group names the user is
    member of using the "groups" key of the result dict.
    """


@hookspec
def devpiserver_indexconfig_defaults(index_type):
    """Returns a dictionary with keys and their defaults for the index
    configuration dictionary.

    It's a good idea to use the plugin name as prefix for the key names
    to avoid clashes between key names in different plugins."""


@hookspec
def devpiserver_on_upload_sync(log, application_url, stage, project, version):
    """Called after release upload.

    Mainly to implement plugins which trigger external services like
    Jenkins to do something upon upload.
    """
