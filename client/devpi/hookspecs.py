from pluggy import HookspecMarker


hookspec = HookspecMarker("devpiclient")


@hookspec(firstresult=True)
def devpiclient_get_password(url, username):
    """Called when password is needed for login.

    Returns the password if there is one, or None if no match is found.
    """
