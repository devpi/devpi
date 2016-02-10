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
    3.0.0b1

.. note::

    This tutorial does not require you to install or use the ``devpi-client``
    package.  Consult :doc:`quickstart-releaseprocess` to learn more 
    about how you can use the ``devpi`` command line tool to
    manage working with uploads, tests and multiple indexes.


start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::
    
    $ devpi-server --start
    2016-02-09 17:34:17,625 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:34:17,626 INFO  NOCTX generated uuid: d2f8672cf4fe446cb534dd79a9f11f8d
    2016-02-09 17:34:17,626 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:34:17,628 INFO  NOCTX DB: Creating schema
    2016-02-09 17:34:17,667 INFO  [Wtx-1] setting password for user u'root'
    2016-02-09 17:34:17,667 INFO  [Wtx-1] created user u'root' with email None
    2016-02-09 17:34:17,667 INFO  [Wtx-1] created root user
    2016-02-09 17:34:17,667 INFO  [Wtx-1] created root/pypi index
    2016-02-09 17:34:17,683 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=4571
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
    Successfully installed simplejson-3.8.1

Let's uninstall it::

    $ pip uninstall -y simplejson
    Uninstalling simplejson-3.8.1:
      Successfully uninstalled simplejson-3.8.1

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    Best match: simplejson 3.8.1
    Downloading http://localhost:3141/root/pypi/+f/b84/41f1053edd9dc/simplejson-3.8.1.tar.gz#md5=b8441f1053edd9dc335ded8c7f98a974
    Processing simplejson-3.8.1.tar.gz
    Writing /tmp/easy_install-mb7ltm/simplejson-3.8.1/setup.cfg
    Running simplejson-3.8.1/setup.py -q bdist_egg --dist-dir /tmp/easy_install-mb7ltm/simplejson-3.8.1/egg-dist-tmp-uEJj0z
    zip_safe flag not set; analyzing archive contents...
    simplejson.tests.__init__: module references __file__
    creating /tmp/docenv/lib/python2.7/site-packages/simplejson-3.8.1-py2.7-linux-x86_64.egg
    Extracting simplejson-3.8.1-py2.7-linux-x86_64.egg to /tmp/docenv/lib/python2.7/site-packages
    Adding simplejson 3.8.1 to easy-install.pth file
    
    Installed /tmp/docenv/lib/python2.7/site-packages/simplejson-3.8.1-py2.7-linux-x86_64.egg
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

We now need to stop the server::

    $ devpi-server --stop
    2016-02-09 17:34:35,898 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:34:35,899 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=4571

and then recreate the search index::

    $ devpi-server --recreate-search-index
    2016-02-09 17:34:36,256 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:34:36,269 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:34:36,284 INFO  [Rtx3] Search-Indexing root/pypi:
    2016-02-09 17:35:01,741 INFO  [Wtx3] setting projects cache for u'simplejson'
    2016-02-09 17:35:25,200 INFO  [Wtx3] Committing 74278 new documents to search index.
    2016-02-09 17:36:21,571 INFO  [Wtx3] Finished committing 74278 documents to search index.
    2016-02-09 17:36:21,639 INFO  [Wtx3] fswriter4: committed: keys: u'root/pypi/+f/b84/41f1053edd9dc/simplejson-3.8.1.tar.gz'

and then start the server again::

    $ devpi-server --start
    2016-02-09 17:36:22,020 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:36:22,021 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /tmp/docenv/bin/devpi-server
    process u'devpi-server' started pid=4707
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

We can now use search with pip::

    $ pip search --index http://localhost:3141/root/pypi/ devpi-client
    /root/pypi/devpi-client     - 

As of version 2.6 devpi-web  does not support showing the description of pypi.python.org packages
(the right hand site of the "-") but it will show the description for your own private indexes.

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
    2016-02-09 17:36:29,294 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:36:29,296 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    server is running with pid 4707

Or stop it::
    
    $ devpi-server --stop
    2016-02-09 17:36:29,746 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:36:29,746 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=4707

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    2016-02-09 17:36:30,163 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:36:30,164 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    last lines of devpi-server log
    2016-02-09 17:36:22,443 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-02-09 17:36:22,494 INFO  NOCTX Found plugin devpi-web-3.0.0b1 (/tmp/docenv/lib/python2.7/site-packages).
    2016-02-09 17:36:22,494 INFO  NOCTX Found plugin devpi-server-3.0.0b1 (/tmp/docenv/lib/python2.7/site-packages).
    2016-02-09 17:36:22,494 INFO  NOCTX Found plugin devpi-server-3.0.0b1 (/tmp/docenv/lib/python2.7/site-packages).
    2016-02-09 17:36:22,494 INFO  NOCTX Found plugin devpi-server-3.0.0b1 (/tmp/docenv/lib/python2.7/site-packages).
    2016-02-09 17:36:22,494 INFO  NOCTX Found plugin devpi-server-3.0.0b1 (/tmp/docenv/lib/python2.7/site-packages).
    2016-02-09 17:36:22,579 INFO  NOCTX devpi-server version: 3.0.0b1
    2016-02-09 17:36:22,579 INFO  NOCTX serverdir: /tmp/home/.devpi/server
    2016-02-09 17:36:22,579 INFO  NOCTX uuid: d2f8672cf4fe446cb534dd79a9f11f8d
    2016-02-09 17:36:22,579 INFO  NOCTX serving at url: http://localhost:3141
    2016-02-09 17:36:22,579 INFO  NOCTX bug tracker: https://bitbucket.org/hpk42/devpi/issues
    2016-02-09 17:36:22,579 INFO  NOCTX IRC: #devpi on irc.freenode.net
    2016-02-09 17:36:22,579 INFO  NOCTX Hit Ctrl-C to quit.
    2016-02-09 17:36:22,641 INFO  [req0] GET /
    2016-02-09 17:36:23,513 INFO  [req1] POST /root/pypi/
    2016-02-09 17:36:28,396 INFO  [NOTI] [Rtx2] Search-Indexing root/pypi:
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
