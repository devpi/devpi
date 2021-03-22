
from pluggy import HookspecMarker

hookspec = HookspecMarker("devpiserver")


@hookspec
def devpiserver_add_parser_options(parser):
    """ called before command line parsing to allow plugins
    to add options through a call to parser.add_argument().
    """


@hookspec
def devpiserver_authcheck_always_ok(request):
    """If the request should always be allowed with +authcheck return True,
    if you want to block it even if other plugins returned True then return False,
    if you can't decide at this stage return None.

    Used for routes like +api and +login."""


@hookspec(firstresult=True)
def devpiserver_authcheck_forbidden(request):
    """If the request should be forbidden with +authcheck,
    this returns True, otherwise None, so other plugins can continue.

    Used by plugins for additional permission checks."""


@hookspec(firstresult=True)
def devpiserver_authcheck_unauthorized(request):
    """If the request should be unauthorized with +authcheck,
    this returns True, otherwise None, so other plugins can continue.

    Used by plugins for additional permission checks."""


@hookspec(firstresult=True)
def devpiserver_cmdline_run(xom):
    """ return an integer with a success code (0 == no errors) if
    you handle the command line invocation, otherwise None.  When
    the first plugin returns an integer, the remaining plugins
    are not called."""


@hookspec
def devpiserver_genconfig(tw, config, argv, writer):
    """ used to write out configuration files.

    - tw is a TerminalWriter instance
    - config gives access to the Config object for things like config.serverdir
    - argv are the commandline arguments
    - writer is a function to write out the config with the following arguments: basename, config
    """


@hookspec
def devpiserver_get_features():
    """ return set containing strings with ids of supported features.

    This is returned in the result of /+api to allow devpi-client to use
    functionality provided by newer devpi-server versions or added by plugins.
    """


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


@hookspec(firstresult=True)
def devpiserver_stage_get_principals_for_pkg_read(ixconfig):
    """Returns principals allowed to read packages.

    Returns a list of principal names. The ``:AUTHENTICATED:`` and
    ``:ANONYMOUS:`` principals are special, see description for acl_upload.
    The first plugin to return principals is used. return None to be skipped.
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


@hookspec(firstresult=True)
def devpiserver_get_identity(request, credentials):
    """Extracts identity from request.

    The policy is the devpi security policy object.

    The credentials are either a tuple with username and password, or None.

    Returns an object with the following attributes, or None if no identity
    could be determined.

        ``username`` - username this identity belongs to
        ``groups`` - a potentially empty list of groups names this identity
        is a member of

    The first plugin to return an identity is used.
    """


@hookspec(warn_on_impl="Use new devpiserver_auth_request hook instead")
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


@hookspec(firstresult=True)
def devpiserver_auth_request(request, userdict, username, password):
    """return authentication validation results.

    If the user is unknown, return None, so other plugins can be tried.

    Otherwise a dict must be returned with a key "status" with one of the
    following values:

        "ok" - authentication succeeded
        "reject" - invalid password, authentication stops

    It is recommended to only use "reject" when explicitly configured to do
    so by the user, otherwise interaction of multiple plugins might have
    unexpected problems.

    Plugins doing network requests should use ``trylast=True`` for the
    hook implementation, so other plugins can potentially shortcut the
    authentication before a network request is required.

    Optionally the plugin can return a list of group names the user is
    member of using the "groups" key of the result dict.
    """


@hookspec
def devpiserver_auth_denials(request, acl, user, stage):
    """EXPERIMENTAL!

    Return None or iterable of tuples with (principal, permission) to be
    added as denials to acl.
    """


@hookspec
def devpiserver_get_stage_customizer_classes():
    """EXPERIMENTAL!

    Returns a list of tuples of index type and customization class.

    The index type string must be unique."""


@hookspec
def devpiserver_indexconfig_defaults(index_type):
    """Returns a dictionary with keys and their defaults for the index
    configuration dictionary.

    It's a good idea to use the plugin name as prefix for the key names
    to avoid clashes between key names in different plugins."""


@hookspec(firstresult=True)
def devpiserver_sro_skip(stage, base_stage):
    """For internal use only!"""


@hookspec
def devpiserver_on_upload_sync(log, application_url, stage, project, version):
    """Called after release upload.

    Mainly to implement plugins which trigger external services like
    Jenkins to do something upon upload.
    """


@hookspec
def devpiserver_on_remove_file(stage, relpath):
    """ called when a relpath is removed from a private stage
    """


@hookspec
def devpiserver_on_replicated_file(stage, project, version, link, serial, back_serial, is_from_mirror):
    """Called when a file was downloaded from master on replica."""


@hookspec
def devpiserver_metrics(request):
    """ called for status view.

        Returns a list of 3 item tuples:
        1. a unique name
        2. the type, either 'counter' or 'gauge'
        3. the value

        The name should be lowercase, must start with a letter and only contain
        letters, numbers and underscores. It should follow this pattern:
        [plugin name]_[name]_[unit]. The unit should be a base unit and not
        use multipliers like kilo, giga, milli etc, use floats for the values.

        For the type use 'counter' for anything that monotonically increases,
        like number of requests or cache hits etc. Use 'gauge' for things like
        the current queue size which can decrease or increase.

        This is very likely to be exposed via Prometheus in the future, so its
        rules apply here as well.
        See https://prometheus.io/docs/instrumenting/writing_clientlibs/
    """
