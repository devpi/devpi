
.. _`quickstart-server`:

Quickstart: permanent install on server/laptop
==========================================================

.. include:: links.rst

This document walks you through setting up your own ``devpi-server``
instance, controlling it with supervisor_ on a UNIX-like system or
launchd_ on Mac OS X and (optionally) serving it through nginx_ on a
UNIX-like system. It also shows how to create a first user and index.

Note that the :doc:`the pypi-mirroring quickstart
<quickstart-pypimirror>` already discusses the ``devpi-server
--start|--log|--stop`` background-server control options which you might
use to integrate with existing ``init.d`` or similar infrastructure.

Installing devpi-server
-----------------------

Install or upgrade ``devpi-server``::

    pip install -U devpi-server
    # if you want the web interface
    pip install -U devpi-web


And let's check the version::

    $ devpi-server --version
    2.6.0

Installing devpi server and client
---------------------------------------------

.. 
    $ devpi-server --stop
    2016-01-28 23:54:51,428 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-01-28 23:54:51,429 INFO  NOCTX generated uuid: 1477c57104084bac8e4b041e5af73f48
    2016-01-28 23:54:51,429 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-01-28 23:54:51,430 INFO  NOCTX DB: Creating schema
    2016-01-28 23:54:51,446 INFO  [Wtx-1] setting password for user u'root'
    2016-01-28 23:54:51,446 INFO  [Wtx-1] created user u'root' with email None
    2016-01-28 23:54:51,446 INFO  [Wtx-1] created root user
    2016-01-28 23:54:51,446 INFO  [Wtx-1] created root/pypi index
    2016-01-28 23:54:51,461 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    no server found

..
    $ rm -rf ~/.devpi/server

When started afresh, ``devpi-server`` will not contain any users
or indexes except for the root user and the ``root/pypi`` index
(see :ref:`using root/pypi index <install_first>`) which represents
and caches https://pypi.python.org packages.  Let's start a server
for the purposes of this tutorial in the background::

    $ devpi-server --port 4040 --start
    2016-01-28 23:54:52,001 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-01-28 23:54:52,002 INFO  NOCTX generated uuid: 616c846232c54140962ce6b0354b4ac9
    2016-01-28 23:54:52,002 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-01-28 23:54:52,002 INFO  NOCTX DB: Creating schema
    2016-01-28 23:54:52,040 INFO  [Wtx-1] setting password for user u'root'
    2016-01-28 23:54:52,041 INFO  [Wtx-1] created user u'root' with email None
    2016-01-28 23:54:52,041 INFO  [Wtx-1] created root user
    2016-01-28 23:54:52,041 INFO  [Wtx-1] created root/pypi index
    2016-01-28 23:54:52,056 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:4040
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server --port 4040
    process u'devpi-server' started pid=18815
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

The ``--start`` option will run a server in the background which
you can further control with the "background server options", see 
output of ``devpi-server -h`` at the end.

The server will listen on ``http://localhost:4040`` and also serve
the devpi web interface if you have ``devpi-web`` installed.

In order to manage users and indices on our fresh server let's also
install the ``devpi-client`` package::

    $ pip install -U --pre -q devpi-client
    /tmp/docenv/local/lib/python2.7/site-packages/pip/_vendor/requests/packages/urllib3/util/ssl_.py:315: SNIMissingWarning: An HTTPS request has been made, but the SNI (Subject Name Indication) extension to TLS is not available on this platform. This may cause the server to present an incorrect TLS certificate, which can cause validation failures. For more information, see https://urllib3.readthedocs.org/en/latest/security.html#snimissingwarning.
      SNIMissingWarning
    /tmp/docenv/local/lib/python2.7/site-packages/pip/_vendor/requests/packages/urllib3/util/ssl_.py:120: InsecurePlatformWarning: A true SSLContext object is not available. This prevents urllib3 from configuring SSL appropriately and may cause certain SSL connections to fail. For more information, see https://urllib3.readthedocs.org/en/latest/security.html#insecureplatformwarning.
      InsecurePlatformWarning
You can install this client software on different hosts if you
`configured nginx`_.

.. _auth:

Connecting to the server
++++++++++++++++++++++++++++++++++

If you `configured nginx`_, you can use the ``server_name``
variable content for connecting to the server, instead of the localhost.
For purposes of this tutorial, we use the URL
``http://localhost:4040`` of the background tutorial server we started above::

    $ devpi use http://localhost:4040
    using server: http://localhost:4040/ (not logged in)
    no current index: type 'devpi use -l' to discover indices
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no

At this point we are not connected to any index, just to the
root server.   And we are not logged in.

setting the root password
++++++++++++++++++++++++++++++++++

The first thing to do is to set a password for the ``root`` user.
For that we first need to login::

    $ devpi login root --password ''
    logged in 'root', credentials valid for 10.00 hours

and can then change it::

    $ devpi user -m root password=123
    user modified: root

Let's verify we don't have any other users::

    $ devpi user -l
    root

The root user can modify any index and any user configuration.
As we don't plan to work further with the root user, we can log off::

    $ devpi logoff
    login information deleted

Registering a new user
++++++++++++++++++++++++++++++++

Let's register ourselves a new regular non-root user::

    $ devpi user -c alice password=456  email=alice@example.com
    user created: alice

and then login::

    $ devpi login alice --password=456
    logged in 'alice', credentials valid for 10.00 hours

Alice can now create her new ``dev`` index::

    $ devpi index -c dev
    http://localhost:4040/alice/dev:
      type=stage
      bases=root/pypi
      volatile=True
      acl_upload=alice
      mirror_whitelist=

and use it ::

    $ devpi use alice/dev
    current devpi index: http://localhost:4040/alice/dev (logged in as alice)
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no

Our ``alice/dev`` index derives from ``root/pypi`` by default
which makes all pypi.python.org releases available.


automatically setting pip/easy_install config files
++++++++++++++++++++++++++++++++++++++++++++++++++++

You can cause devpi to set ``$HOME`` configuration files which will
cause ``pip`` and ``easy_install`` to use our in-use index server::

    $ devpi use --set-cfg alice/dev
    current devpi index: http://localhost:4040/alice/dev (logged in as alice)
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no

This will modify or create common configuration files in your home directory
so that subsequent ``pip`` or ``easy_install`` invocations will work against
the ``user/indexname`` index.   You can configure ``devpi`` to perform
this configuration modification::

    $ devpi use --always-set-cfg=yes
    current devpi index: http://localhost:4040/alice/dev (logged in as alice)
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: yes

This will imply ``--set-cfg`` on all subsequent ``devpi use ...`` operations.

Installing, uploading, testing and releasing
+++++++++++++++++++++++++++++++++++++++++++++++++

You may now continue with install, test and release activities
as described in the :ref:`release process quickstart <quickstart_release_steps>`.

Stopping the server
++++++++++++++++++++++++++++++++++++++++++

Let's not forget to stop our background tutorial server::

    $ devpi-server --stop
    2016-01-28 23:55:06,556 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-01-28 23:55:06,557 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=18815

