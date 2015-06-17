from pluggy import HookspecMarker

hookspec = HookspecMarker("devpiweb")


@hookspec
def devpiweb_get_status_info(request):
    """Called on every request to gather status information.

    Returns a list of dictionaries with keys ``status`` and ``msg``, where
    status is ``warn`` or ``fatal``.
    """
