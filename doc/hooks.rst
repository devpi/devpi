

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

There is one hook to enable authentication from external sources::

    devpiserver_auth_user(model, username, password):
        """Needs to validate the username and password.

        In case of valid credentials a list must be returned which optionally
        contains the group names the user is member of.
        If returning False, the authentication for the user fails. No other
        plugin or devpi-server internals can change that.
        If the hook returns None, then the next plugin or the devpi-server
        internal authentication is used.
        """

The model argument should only be used to check whether a user exists in
``devpi-server`` with ``model.get_user(username)``. You are on your own if
you use it for anything else.


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
