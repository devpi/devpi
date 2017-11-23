.. include:: links.rst

Quickstart: running a pypi mirror on your laptop
----------------------------------------------------

This quickstart document let's you quickly run and manage ``devpi-server``
for serving an efficient self-updating PyPI caching mirror on your laptop,
suitable for offline operations after an initial cache fill.

Installing devpi-server
++++++++++++++++++++++++++++++++++

Install the ``devpi-server`` package on our machine::

    pip install -q -U devpi-server

Show version::

    $ devpi-server --version
    4.3.1

.. note::

    This tutorial does not require you to install or use the ``devpi-client``
    package.  Consult :doc:`quickstart-releaseprocess` to learn more
    about how you can use the ``devpi`` command line tool to
    manage working with uploads, tests and multiple indexes.


start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::

    $ devpi-server --start --init
    2017-11-23 14:27:37,421 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:27:37,421 INFO  NOCTX generated uuid: 848a06f3d65f42b1b9b6b20656044b3d
    2017-11-23 14:27:37,422 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:27:37,430 INFO  NOCTX DB: Creating schema
    2017-11-23 14:27:37,437 INFO  [Wtx-1] setting password for user 'root'
    2017-11-23 14:27:37,437 INFO  [Wtx-1] created user 'root' with email None
    2017-11-23 14:27:37,437 INFO  [Wtx-1] created root user
    2017-11-23 14:27:37,437 INFO  [Wtx-1] created root/pypi index
    2017-11-23 14:27:37,439 INFO  [Wtx-1] fswriter0: committed: keys: '.config','root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/devpi/devpi/bin/devpi-server
    process 'devpi-server' started pid=43495
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

You now have a server listening on ``http://localhost:3141``.

.. _`install_first`:

install your first package with pip/easy_install
+++++++++++++++++++++++++++++++++++++++++++++++++++++

Both pip_ and easy_install_ support the ``-i`` option to specify
an index server url.  We use it to point installers to a special
``root/pypi`` index, served by ``devpi-server`` by default.
Let's install the ``simplejson`` package as a test from our cache::

    $ pip install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Collecting simplejson
      Downloading http://localhost:3141/root/pypi/+f/f16/ee9594b5e84c6/simplejson-3.12.0-py3-none-any.whl (51kB)
    Installing collected packages: simplejson
    Successfully installed simplejson-3.12.0

Let's uninstall it::

    $ pip uninstall -y simplejson
    Uninstalling simplejson-3.12.0:
      Successfully uninstalled simplejson-3.12.0

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    Downloading http://localhost:3141/root/pypi/+f/048/548acae58984b/simplejson-3.12.0.tar.gz#md5=048548acae58984b3e939b3bcf182c8e
    Best match: simplejson 3.12.0
    Processing simplejson-3.12.0.tar.gz
    Writing /tmp/easy_install-asly2xzd/simplejson-3.12.0/setup.cfg
    Running simplejson-3.12.0/setup.py -q bdist_egg --dist-dir /tmp/easy_install-asly2xzd/simplejson-3.12.0/egg-dist-tmp-505x3w7q
    zip_safe flag not set; analyzing archive contents...
    simplejson.__pycache__._speedups.cpython-34: module references __file__
    simplejson.tests.__pycache__.__init__.cpython-34: module references __file__
    creating /private/tmp/docenv/lib/python3.4/site-packages/simplejson-3.12.0-py3.4-macosx-10.12-x86_64.egg
    Extracting simplejson-3.12.0-py3.4-macosx-10.12-x86_64.egg to /private/tmp/docenv/lib/python3.4/site-packages
    Adding simplejson 3.12.0 to easy-install.pth file
    
    Installed /private/tmp/docenv/lib/python3.4/site-packages/simplejson-3.12.0-py3.4-macosx-10.12-x86_64.egg
    Processing dependencies for simplejson
    Finished processing dependencies for simplejson

Feel free to install any other package.  If you encounter lookup/download
issues when installing a public pypi package, please report the offending
package name to the `devpi issue tracker`_, at best including
the output of ``devpi-server --log``.  We constantly aim to get the
mirroring 100% bug free and compatible to pypi.python.org.

.. _`pip search`:

using ``pip search``
++++++++++++++++++++

To enable ``pip search`` functionality, you should install the ``devpi-web`` plugin
**before you initially start devpi-server**.  As we started a server instance
above already we'll need to trigger recreating the search index. But first let's
install the plugin which we can safely do while the server is running::

    $ pip install -q -U devpi-web
      Could not find a version that satisfies the requirement repoze.lru>=0.6 (from devpi-server>=3.0.0.dev2->devpi-web) (from versions: )
    No matching distribution found for repoze.lru>=0.6 (from devpi-server>=3.0.0.dev2->devpi-web)

We now need to stop the server::

    $ devpi-server --stop
    2017-11-23 14:28:37,323 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:28:37,324 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=43495

and then recreate the search index::

    $ devpi-server --recreate-search-index
    2017-11-23 14:28:38,055 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:28:38,056 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:28:38,090 INFO  [Rtx4] Search-Indexing root/pypi:
    2017-11-23 14:29:51,810 INFO  [Wtx4] setting projects cache for 'simplejson'
    2017-11-23 14:30:06,819 INFO  [Wtx4] Committing 122544 new documents to search index.
    2017-11-23 14:31:48,419 INFO  [Wtx4] Finished committing 122544 documents to search index.
    2017-11-23 14:31:48,487 INFO  [Wtx4] fswriter5: committed: keys: 'root/pypi/+f/048/548acae58984b/simplejson-3.12.0.tar.gz','root/pypi/+f/f16/ee9594b5e84c6/simplejson-3.12.0-py3-none-any.whl'

and then start the server again::

    $ devpi-server --start
    2017-11-23 14:31:49,234 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:31:49,235 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /tmp/docenv/bin/devpi-server
    process 'devpi-server' started pid=43698
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

We can now use search with pip::

    $ pip search --index http://localhost:3141/root/pypi/ devpi-client
    devpi-client ()             - [root/pypi]
    devpi-client-extensions ()  - [root/pypi]

.. note::

   Currently devpi-web does not support showing the description of pypi.python.org packages
   (the right hand site of the "-") but it will show the description for projects which you
   uploaded to your own private indexes.

.. _perminstallindex:

permanent index configuration for pip
+++++++++++++++++++++++++++++++++++++++++++++++++++++

To avoid having to re-type index URLs with ``pip`` or ``easy-install`` ,
you can configure pip by setting the index-url entry in your
``$HOME/.pip/pip.conf`` (posix) or ``$HOME/pip/pip.ini`` (windows).
Let's do it for the ``root/pypi`` index::

    # $HOME/.pip/pip.conf
    [global]
    index-url = http://localhost:3141/root/pypi/+simple/

Alternatively, you can add a special environment variable
to your shell settings (e.g. ``.bashrc``):

   export PIP_INDEX_URL=http://localhost:3141/root/pypi/+simple/

For `pip search`_ you need a ``[search]`` section in your ``pip.conf``::

    # $HOME/.pip/pip.conf
    [global]
    index-url = http://localhost:3141/root/pypi/+simple/

    [search]
    index = http://localhost:3141/root/pypi/


permanent index configuration for easy_install
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++

You can configure ``easy_install`` by an entry in
the ``$HOME/.pydistutils.cfg`` file::

    # $HOME/.pydistutils.cfg:
    [easy_install]
    index_url = http://localhost:3141/root/pypi/+simple/


Checking and stopping the background server
++++++++++++++++++++++++++++++++++++++++++++

At any time you can check the background server status with::

    $ devpi-server --status
    2017-11-23 14:31:52,089 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:31:52,090 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    server is running with pid 43698

Or stop it::

    $ devpi-server --stop
    2017-11-23 14:31:52,808 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:31:52,809 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=43698

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    2017-11-23 14:31:53,535 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:31:53,536 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    last lines of devpi-server log
    2017-11-23 14:31:49,888 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2017-11-23 14:31:49,970 INFO  NOCTX Found plugin devpi-web-3.2.1 (/private/tmp/docenv/lib/python3.4/site-packages).
    2017-11-23 14:31:49,970 INFO  NOCTX Found plugin devpi-server-4.3.1 (/private/tmp/docenv/lib/python3.4/site-packages).
    2017-11-23 14:31:49,970 INFO  NOCTX Found plugin devpi-server-4.3.1 (/private/tmp/docenv/lib/python3.4/site-packages).
    2017-11-23 14:31:49,970 INFO  NOCTX Found plugin devpi-server-4.3.1 (/private/tmp/docenv/lib/python3.4/site-packages).
    2017-11-23 14:31:49,970 INFO  NOCTX Found plugin devpi-server-4.3.1 (/private/tmp/docenv/lib/python3.4/site-packages).
    2017-11-23 14:31:50,044 INFO  NOCTX devpi-server version: 4.3.1
    2017-11-23 14:31:50,044 INFO  NOCTX serverdir: /tmp/home/.devpi/server
    2017-11-23 14:31:50,044 INFO  NOCTX uuid: 848a06f3d65f42b1b9b6b20656044b3d
    2017-11-23 14:31:50,044 INFO  NOCTX serving at url: http://localhost:3141 (might be http://[localhost]:3141 for IPv6)
    2017-11-23 14:31:50,044 INFO  NOCTX using 50 threads
    2017-11-23 14:31:50,044 INFO  NOCTX bug tracker: https://github.com/devpi/devpi/issues
    2017-11-23 14:31:50,044 INFO  NOCTX IRC: #devpi on irc.freenode.net
    2017-11-23 14:31:50,045 INFO  NOCTX Hit Ctrl-C to quit.
    2017-11-23 14:31:50,182 INFO  [req0] GET /
    2017-11-23 14:31:50,920 INFO  [req1] POST /root/pypi/
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
