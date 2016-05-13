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
    4.0.0

.. note::

    This tutorial does not require you to install or use the ``devpi-client``
    package.  Consult :doc:`quickstart-releaseprocess` to learn more 
    about how you can use the ``devpi`` command line tool to
    manage working with uploads, tests and multiple indexes.


start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::
    
    $ devpi-server --start
    2016-05-13 17:46:29,171 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:46:29,172 INFO  NOCTX generated uuid: 36769b3f17e041279686e807d596c5ae
    2016-05-13 17:46:29,173 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:46:29,174 INFO  NOCTX DB: Creating schema
    2016-05-13 17:46:29,218 INFO  [Wtx-1] setting password for user u'root'
    2016-05-13 17:46:29,218 INFO  [Wtx-1] created user u'root' with email None
    2016-05-13 17:46:29,218 INFO  [Wtx-1] created root user
    2016-05-13 17:46:29,218 INFO  [Wtx-1] created root/pypi index
    2016-05-13 17:46:29,225 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=23223
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

    $ pip install -i http://localhost:3141/root/pypi/ simplejson
    Collecting simplejson
    Installing collected packages: simplejson
    Successfully installed simplejson-3.8.2
    You are using pip version 8.1.1, however version 8.1.2 is available.
    You should consider upgrading via the 'pip install --upgrade pip' command.

Let's uninstall it::

    $ pip uninstall -y simplejson
    Uninstalling simplejson-3.8.2:
      Successfully uninstalled simplejson-3.8.2
    You are using pip version 8.1.1, however version 8.1.2 is available.
    You should consider upgrading via the 'pip install --upgrade pip' command.

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    Best match: simplejson 3.8.2
    Downloading http://localhost:3141/root/pypi/+f/53b/1371bbf883b12/simplejson-3.8.2.tar.gz#md5=53b1371bbf883b129a12d594a97e9a18
    Processing simplejson-3.8.2.tar.gz
    Writing /tmp/easy_install-gDLAKV/simplejson-3.8.2/setup.cfg
    Running simplejson-3.8.2/setup.py -q bdist_egg --dist-dir /tmp/easy_install-gDLAKV/simplejson-3.8.2/egg-dist-tmp-1z00wm
    zip_safe flag not set; analyzing archive contents...
    simplejson.tests.__init__: module references __file__
    creating /tmp/docenv/lib/python2.7/site-packages/simplejson-3.8.2-py2.7-linux-x86_64.egg
    Extracting simplejson-3.8.2-py2.7-linux-x86_64.egg to /tmp/docenv/lib/python2.7/site-packages
    Adding simplejson 3.8.2 to easy-install.pth file
    
    Installed /tmp/docenv/lib/python2.7/site-packages/simplejson-3.8.2-py2.7-linux-x86_64.egg
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
    2016-05-13 17:47:05,134 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:47:05,135 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=23223

and then recreate the search index::

    $ devpi-server --recreate-search-index
    2016-05-13 17:47:05,603 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:47:05,604 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:47:05,621 INFO  [Rtx3] Search-Indexing root/pypi:
    2016-05-13 17:47:36,217 INFO  [Wtx3] setting projects cache for u'simplejson'
    2016-05-13 17:48:00,488 INFO  [Wtx3] Committing 80502 new documents to search index.
    2016-05-13 17:48:56,017 INFO  [Wtx3] Finished committing 80502 documents to search index.
    2016-05-13 17:48:56,074 INFO  [Wtx3] fswriter4: committed: keys: u'root/pypi/+f/53b/1371bbf883b12/simplejson-3.8.2.tar.gz'

and then start the server again::

    $ devpi-server --start
    2016-05-13 17:48:56,541 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:48:56,542 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /tmp/docenv/bin/devpi-server
    process u'devpi-server' started pid=23499
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

We can now use search with pip::

    $ pip search --index http://localhost:3141/root/pypi/ devpi-client
    /root/pypi/devpi-client ()  - 
    You are using pip version 8.1.1, however version 8.1.2 is available.
    You should consider upgrading via the 'pip install --upgrade pip' command.

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
    2016-05-13 17:49:04,401 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:49:04,402 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    server is running with pid 23499

Or stop it::
    
    $ devpi-server --stop
    2016-05-13 17:49:04,931 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:49:04,932 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=23499

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    2016-05-13 17:49:05,390 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:49:05,391 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    last lines of devpi-server log
    2016-05-13 17:48:57,083 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 17:48:57,148 INFO  NOCTX Found plugin devpi-web-3.1.0 (/tmp/docenv/lib/python2.7/site-packages).
    2016-05-13 17:48:57,149 INFO  NOCTX Found plugin devpi-server-4.0.0 (/tmp/docenv/lib/python2.7/site-packages).
    2016-05-13 17:48:57,149 INFO  NOCTX Found plugin devpi-server-4.0.0 (/tmp/docenv/lib/python2.7/site-packages).
    2016-05-13 17:48:57,149 INFO  NOCTX Found plugin devpi-server-4.0.0 (/tmp/docenv/lib/python2.7/site-packages).
    2016-05-13 17:48:57,149 INFO  NOCTX Found plugin devpi-server-4.0.0 (/tmp/docenv/lib/python2.7/site-packages).
    2016-05-13 17:48:57,222 INFO  NOCTX devpi-server version: 4.0.0
    2016-05-13 17:48:57,223 INFO  NOCTX serverdir: /tmp/home/.devpi/server
    2016-05-13 17:48:57,223 INFO  NOCTX uuid: 36769b3f17e041279686e807d596c5ae
    2016-05-13 17:48:57,223 INFO  NOCTX serving at url: http://localhost:3141
    2016-05-13 17:48:57,223 INFO  NOCTX bug tracker: https://bitbucket.org/hpk42/devpi/issues
    2016-05-13 17:48:57,223 INFO  NOCTX IRC: #devpi on irc.freenode.net
    2016-05-13 17:48:57,223 INFO  NOCTX Hit Ctrl-C to quit.
    2016-05-13 17:48:57,267 INFO  [req0] GET /
    2016-05-13 17:48:58,123 INFO  [req1] POST /root/pypi/
    2016-05-13 17:49:03,621 INFO  [NOTI] [Rtx2] Search-Indexing root/pypi:
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
