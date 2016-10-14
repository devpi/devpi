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
    4.1.1

.. note::

    This tutorial does not require you to install or use the ``devpi-client``
    package.  Consult :doc:`quickstart-releaseprocess` to learn more
    about how you can use the ``devpi`` command line tool to
    manage working with uploads, tests and multiple indexes.


start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::

    $ devpi-server --start
    2016-10-11 13:15:28,819 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:15:28,819 INFO  NOCTX generated uuid: 3f50f0fcf91d4110884e11cbd8b9e441
    2016-10-11 13:15:28,820 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:15:28,822 INFO  NOCTX DB: Creating schema
    2016-10-11 13:15:28,835 INFO  [Wtx-1] setting password for user 'root'
    2016-10-11 13:15:28,835 INFO  [Wtx-1] created user 'root' with email None
    2016-10-11 13:15:28,835 INFO  [Wtx-1] created root user
    2016-10-11 13:15:28,835 INFO  [Wtx-1] created root/pypi index
    2016-10-11 13:15:28,838 INFO  [Wtx-1] fswriter0: committed: keys: 'root/.config','.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/devpi/devpi/bin/devpi-server
    process 'devpi-server' started pid=29822
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
    Installing collected packages: simplejson
    Successfully installed simplejson-3.8.2

Let's uninstall it::

    $ pip uninstall -y simplejson
    Uninstalling simplejson-3.8.2:
      Successfully uninstalled simplejson-3.8.2

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    Downloading http://localhost:3141/root/pypi/+f/53b/1371bbf883b12/simplejson-3.8.2.tar.gz#md5=53b1371bbf883b129a12d594a97e9a18
    Best match: simplejson 3.8.2
    Processing simplejson-3.8.2.tar.gz
    Writing /tmp/easy_install-bqzxeav1/simplejson-3.8.2/setup.cfg
    Running simplejson-3.8.2/setup.py -q bdist_egg --dist-dir /tmp/easy_install-bqzxeav1/simplejson-3.8.2/egg-dist-tmp-0spoth3a
    zip_safe flag not set; analyzing archive contents...
    simplejson.__pycache__._speedups.cpython-35: module references __file__
    simplejson.tests.__pycache__.__init__.cpython-35: module references __file__
    creating /tmp/docenv/lib/python3.5/site-packages/simplejson-3.8.2-py3.5-linux-x86_64.egg
    Extracting simplejson-3.8.2-py3.5-linux-x86_64.egg to /tmp/docenv/lib/python3.5/site-packages
    Adding simplejson 3.8.2 to easy-install.pth file
    
    Installed /tmp/docenv/lib/python3.5/site-packages/simplejson-3.8.2-py3.5-linux-x86_64.egg
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
    2016-10-11 13:15:48,896 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:15:48,898 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=29822

and then recreate the search index::

    $ devpi-server --recreate-search-index
    2016-10-11 13:15:49,722 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:15:49,724 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:15:49,741 INFO  [Rtx3] Search-Indexing root/pypi:
    2016-10-11 13:16:38,958 INFO  [Wtx3] setting projects cache for 'simplejson'
    2016-10-11 13:17:27,275 INFO  [Wtx3] Committing 90479 new documents to search index.
    2016-10-11 13:19:32,739 INFO  [Wtx3] Finished committing 90479 documents to search index.
    2016-10-11 13:19:32,816 INFO  [Wtx3] fswriter4: committed: keys: 'root/pypi/+f/53b/1371bbf883b12/simplejson-3.8.2.tar.gz'

and then start the server again::

    $ devpi-server --start
    2016-10-11 13:19:33,669 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:19:33,671 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /tmp/docenv/bin/devpi-server
    process 'devpi-server' started pid=30139
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

We can now use search with pip::

    $ pip search --index http://localhost:3141/root/pypi/ devpi-client
    /root/pypi/devpi-client ()  - 

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
    2016-10-11 13:19:36,419 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:19:36,420 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    server is running with pid 30139

Or stop it::

    $ devpi-server --stop
    2016-10-11 13:19:37,214 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:19:37,215 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=30139

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    2016-10-11 13:19:37,998 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:19:38,000 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    last lines of devpi-server log
    2016-10-11 13:19:34,494 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-10-11 13:19:34,578 INFO  NOCTX Found plugin devpi-web-3.1.1 (/tmp/docenv/lib/python3.5/site-packages).
    2016-10-11 13:19:34,578 INFO  NOCTX Found plugin devpi-server-4.1.1 (/tmp/docenv/lib/python3.5/site-packages).
    2016-10-11 13:19:34,578 INFO  NOCTX Found plugin devpi-server-4.1.1 (/tmp/docenv/lib/python3.5/site-packages).
    2016-10-11 13:19:34,578 INFO  NOCTX Found plugin devpi-server-4.1.1 (/tmp/docenv/lib/python3.5/site-packages).
    2016-10-11 13:19:34,579 INFO  NOCTX Found plugin devpi-server-4.1.1 (/tmp/docenv/lib/python3.5/site-packages).
    2016-10-11 13:19:34,682 INFO  NOCTX devpi-server version: 4.1.1
    2016-10-11 13:19:34,683 INFO  NOCTX serverdir: /tmp/home/.devpi/server
    2016-10-11 13:19:34,683 INFO  NOCTX uuid: 3f50f0fcf91d4110884e11cbd8b9e441
    2016-10-11 13:19:34,683 INFO  NOCTX serving at url: http://localhost:3141
    2016-10-11 13:19:34,683 INFO  NOCTX bug tracker: https://bitbucket.org/hpk42/devpi/issues
    2016-10-11 13:19:34,683 INFO  NOCTX IRC: #devpi on irc.freenode.net
    2016-10-11 13:19:34,683 INFO  NOCTX Hit Ctrl-C to quit.
    2016-10-11 13:19:34,708 INFO  [req0] GET /
    2016-10-11 13:19:35,530 INFO  [req1] POST /root/pypi/
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
