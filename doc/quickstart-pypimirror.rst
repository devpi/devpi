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
    2.3.0

.. note::

    This tutorial does not require you to install or use the ``devpi-client``
    package.  Consult :doc:`quickstart-releaseprocess` to learn more 
    about how you can use the ``devpi`` command line tool to
    manage working with uploads, tests and multiple indexes.


start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::
    
    $ devpi-server --start
    2015-09-10 11:05:44,373 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:44,374 INFO  NOCTX generated uuid: 468a3072800746b4befa3ec80406f2ec
    2015-09-10 11:05:44,374 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:44,375 INFO  NOCTX DB: Creating schema
    2015-09-10 11:05:44,414 INFO  [Wtx-1] opening sql
    2015-09-10 11:05:44,416 INFO  [Wtx-1] setting password for user u'root'
    2015-09-10 11:05:44,416 INFO  [Wtx-1] created user u'root' with email None
    2015-09-10 11:05:44,416 INFO  [Wtx-1] created root user
    2015-09-10 11:05:44,417 INFO  [Wtx-1] created root/pypi index
    2015-09-10 11:05:44,430 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=21740
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
      Could not find a version that satisfies the requirement simplejson (from versions: )
    No matching distribution found for simplejson

Let's uninstall it::

    $ pip uninstall -y simplejson
    Cannot uninstall requirement simplejson, not installed

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    No local packages or download links found for simplejson
    error: Could not find suitable distribution for Requirement.parse('simplejson')

Feel free to install any other package.  If you encounter lookup/download
issues when installing a public pypi package, please report the offending
package name to the `devpi issue tracker`_, at best including
the output of ``devpi-server --log``.  We constantly aim to get the
mirroring 100% bug free and compatible to pypi.python.org.

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
    2015-09-10 11:05:51,717 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:51,718 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:51,721 INFO  [Wtx1] opening sql
    server is running with pid 21740

Or stop it::
    
    $ devpi-server --stop
    2015-09-10 11:05:52,318 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:52,318 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:52,321 INFO  [Wtx1] opening sql
    killed server pid=21740

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    2015-09-10 11:05:52,918 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:52,918 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:52,921 INFO  [Wtx1] opening sql
    last lines of devpi-server log
    2015-09-10 11:05:45,108 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:45,111 INFO  [Wtx0] opening sql
    2015-09-10 11:05:45,112 INFO  NOCTX retrieving initial name/serial list
    2015-09-10 11:05:49,528 INFO  [Wtx0] opening sql
    2015-09-10 11:05:49,543 INFO  [Wtx0] fswriter1: committed: keys: u'root/pypi/initiallinks'
    2015-09-10 11:05:49,544 INFO  [Rtx1] opening sql
    2015-09-10 11:05:49,582 INFO  NOCTX Found plugin devpi-server-2.2.3.dev0 (/home/hpk/p/devpi/server).
    2015-09-10 11:05:49,582 INFO  NOCTX Found plugin devpi-server-2.2.3.dev0 (/home/hpk/p/devpi/server).
    2015-09-10 11:05:49,582 INFO  NOCTX Found plugin devpi-web-2.4.1.dev0 (/home/hpk/p/devpi/web).
    2015-09-10 11:05:49,669 INFO  NOCTX devpi-server version: 2.3.0
    2015-09-10 11:05:49,669 INFO  NOCTX serverdir: /tmp/home/.devpi/server
    2015-09-10 11:05:49,670 INFO  NOCTX uuid: 468a3072800746b4befa3ec80406f2ec
    2015-09-10 11:05:49,670 INFO  NOCTX serving at url: http://localhost:3141
    2015-09-10 11:05:49,670 INFO  NOCTX bug tracker: https://bitbucket.org/hpk42/devpi/issues
    2015-09-10 11:05:49,670 INFO  NOCTX IRC: #devpi on irc.freenode.net
    2015-09-10 11:05:49,671 INFO  NOCTX Hit Ctrl-C to quit.
    2015-09-10 11:05:49,671 INFO  [NOTI] [Rtx1] opening sql
    2015-09-10 11:05:49,703 INFO  [NOTI] [Rtx1] Search-Indexing root/pypi:
    2015-09-10 11:05:49,703 INFO  [NOTI] [Rtx1] Committing 0 new documents to search index.
    2015-09-10 11:05:49,711 INFO  [NOTI] [Rtx1] Finished committing 0 documents to search index.
    2015-09-10 11:05:49,711 INFO  [NOTI] [Rtx1] finished initial indexing op
    2015-09-10 11:05:49,726 INFO  [req0] GET /
    2015-09-10 11:05:49,728 INFO  [req0] [Rtx1] opening sql
    2015-09-10 11:05:50,325 INFO  [req1] GET /root/pypi/simplejson/
    2015-09-10 11:05:50,326 INFO  [req1] [Rtx1] opening sql
    2015-09-10 11:05:50,329 INFO  [req2] GET /root/pypi/+simple/simplejson
    2015-09-10 11:05:50,329 INFO  [req2] [Rtx1] opening sql
    2015-09-10 11:05:50,330 ERROR [req2] [Rtx1] no such project u'simplejson'
    2015-09-10 11:05:50,355 INFO  [req3] GET /root/pypi/simplejson/
    2015-09-10 11:05:50,356 INFO  [req3] [Rtx1] opening sql
    2015-09-10 11:05:50,358 INFO  [req4] GET /root/pypi/+simple/simplejson
    2015-09-10 11:05:50,359 INFO  [req4] [Rtx1] opening sql
    2015-09-10 11:05:50,359 ERROR [req4] [Rtx1] no such project u'simplejson'
    2015-09-10 11:05:51,143 INFO  [req5] GET /root/pypi/+simple/simplejson/
    2015-09-10 11:05:51,144 INFO  [req5] [Rtx1] opening sql
    2015-09-10 11:05:51,144 ERROR [req5] [Rtx1] no such project u'simplejson'
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
