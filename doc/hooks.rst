

devpi-server plugin hooks (experimental)
============================================

``devpi-server-2.0`` introduced an experimental Plugin system in order
to decouple ``devpi-web`` from core operations.  As the 2.0 series becomes more
battle tested we expect the plugin API to stabilize and be useable from
other prospective extensions.

.. note::

    The hook and plugin explanations here are not yet sufficient to write
    your own plugin just from looking at the documentation.  The docs
    are meant for recording design decisions and notes about the plugin
    hooks. You will probably have to read up on the source code and
    communicate with the mailing list or IRC channel.


hook semantics for authentication
---------------------------------

To get the username and password from the request, the following hook is used::

    def devpiserver_auth_credentials(request):
        """Extracts username and password from request.

        Returns a tuple with (username, password) if credentials could be
        extracted, or None if no credentials were found.

        The first plugin to return credentials is used, the order of plugin
        calls is undefined.
        """

There is one hook to enable authentication from external sources::

    devpiserver_auth_user(userdict, username, password):
        """Needs to validate the username and password.

        A dict must be returned with a key "status" with one of the following
        values:
            "ok" - authentication succeeded
            "unknown" - no matching user, other plugins are tried
            "reject" - invalid password, authentication stops

        Optionally the plugin can return a list of group names the user is
        member of using the "groups" key of the result dict.
        """


hook semantics for metadata changes and uploads
------------------------------------------------

There are currently two hooks notifying plugins of changes::

    devpiserver_on_changed_versiondata(stage, projectname, version, metadata)
    # metadata may be empty in which case the version was deleted

    devpiserver_on_upload(stage, projectname, version, link)
    # link.entry.file_exists() may be false because a more recent
    # revision deleted the file (and files are not revisioned)
    # This hook is currently NOT called for the implicit "caching" 
    # uploads to the pypi mirror.

- Both hooks are called within a read-transaction pointing at the serial
  where the change occured. This means that hooks may read values but
  they cannot write values.

- hook subscribers are called after a transaction has finally
  committed and thus cannot influence the outcome of the transaction
  performing the change.  It is also possible that subscribers
  are called much later because some subscribers may take long
  to complete.

- subscriptions are persistent in the sense that if there is a lag of N
  pending serials where subscribers need to be called, a process restart
  will continue to call the appropriate subscribers after startup.

- hook subscribers are called one after another from the same
  dedicated thread.  Exceptions of a subscriber are logged
  but will not prevent the execution of other subscribers.

- the hook calling thread is managed from the KeyFS instance.

- the hooks are called in the same way from within a master and
  replica process.

- hook subscribers must honour **idempotency**: they should properly
  deal with getting executed multiple times for each serial.


hook semantics for index configuration settings
------------------------------------------------

Plugins can add key names and default values to the index configuration::

    def devpiserver_indexconfig_defaults():
        """Returns a dictionary with keys and their defaults for the index
        configuration dictionary.

        It's best to use the plugin name as prefix to avoid clashes between
        key names in different plugins."""
