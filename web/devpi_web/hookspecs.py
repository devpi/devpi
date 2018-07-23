from pluggy import HookspecMarker

hookspec = HookspecMarker("devpiweb")


@hookspec
def devpiweb_get_status_info(request):
    """Called on every request to gather status information.

    Returns a list of dictionaries with keys ``status`` and ``msg``, where
    status is ``warn`` or ``fatal``.
    """


@hookspec
def devpiweb_indexer_backend():
    """ return dict containing indexer backend info.

    The following keys are defined:

        "indexer" - the class implementing the indexer API
        "name" - name for selection from command line
        "description" - a short description for the commandline help
    """
