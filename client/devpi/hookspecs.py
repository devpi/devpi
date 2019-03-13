from pluggy import HookspecMarker


hookspec = HookspecMarker("devpiclient")


@hookspec(firstresult=True)
def devpiclient_get_password(url, username):
    """Called when password is needed for login.

    Returns the password if there is one, or None if no match is found.
    """


@hookspec()
def devpiclient_subcommands():
    """ Called to discover subcommands for devpi-client.

    Returns a list of 3 item tuples.

    1. a function taking one argument ``parser`` which is an argparse subparser
    2. the name of the command
    3. a location for the handler function in the form "module:name"

    The handler function gets two arguments: ``hub`` and ``args``.
    """
