

devpi-server plugin hooks (experimental)
============================================

``devpi-server-3.0`` provides a reasonably but not completely stable Plugin system 
in order to decouple ``devpi-web`` from core operations.  As the 3.0 series becomes more
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

    def devpiserver_get_credentials(request):
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


hook semantics for creating of indexes
--------------------------------------

In order to act on creation of new indexes::

    devpiserver_stage_created(stage)


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


hook semantics for package uploads
-----------------------------------

The devpiserver_on_upload_sync is called during the request and can write to
the log. It is meant for triggering CI servers and similar use cases::

    def devpiserver_on_upload_sync(log, application_url, stage, projectname, version):
        """Called after release upload.

        Mainly to implement plugins which trigger external services like
        Jenkins to do something upon upload.
        """

The application_url is the base URL of the devpi-server request and can be
used for uploading test results etc.


hook semantics for index configuration settings
------------------------------------------------

Plugins can add key names and default values to the index configuration::

    def devpiserver_indexconfig_defaults():
        """Returns a dictionary with keys and their defaults for the index
        configuration dictionary.

        It's best to use the plugin name as prefix to avoid clashes between
        key names in different plugins."""


hook semantics for mirror indexes
---------------------------------

Plugins can process the initial list of projectnames when a mirror loads it::

    def devpiserver_mirror_initialnames(stage, projectnames):
        """called with a mirror stage and a list of projectnames, initially
        retrieved from the mirrored remote site. """


hook semantics for storage backends
-----------------------------------

Plugins can provide custom storage backends. The storage API is still experimental::

    def devpiserver_storage_backend(settings):
        """ return dict containing storage backend info.

        The following keys are defined:

            "storage" - the class implementing the storage API
            "name" - name for selection from command line
            "description" - a short description for the commandline help
        """



devpi-web plugin hooks (experimental)
============================================

hook semantics for status messages in web ui
------------------------------------------------

Plugins can show server status messages in the web interface::

  def devpiweb_get_status_info(request):
      """Called on every request to gather status information.

      Returns a list of dictionaries with keys ``status`` and ``msg``, where
      status is ``warn`` or ``fatal``.
      """



devpi-client plugin hooks (experimental)
============================================

hook semantics for password prompt
------------------------------------------------

Plugins can return passwords based on username and server url::

  def devpiclient_get_password(url, username):
      """Called when password is needed for login.

      Returns the password if there is one, or None if no match is found.
      """
