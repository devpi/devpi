
.. include:: links.rst

Quickstart: running a pypi mirror on your laptop
----------------------------------------------------

This quickstart document let's you quickly run and manage ``devpi-server``
for serving an efficient self-updating PyPI caching mirror on your laptop,
suitable for offline operations after an initial cache fill.

Installing devpi-server
++++++++++++++++++++++++++++++++++

Install the ``devpi-server`` package on our machine::

	pip install -U devpi-server

start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::
    
    $ devpi-server --start
    starting background devpi-server at http://localhost:3141
    /home/hpk/p/devpi/doc/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process 'devpi-server' started pid=325
    devpi-server process startup detected
    logfile is at /home/hpk/p/devpi/doc/.devpi/server/.xproc/devpi-server/xprocess.log

You now have a server listning on ``http://localhost:3141``.

.. _`install_first`:

install your first package with pip/easy_install
+++++++++++++++++++++++++++++++++++++++++++++++++++++

Both pip_ and easy_install_ support the ``-i`` option to specify
an index server url.  We use it to point installers to a special
``root/pypi`` index, served by ``devpi-server`` by default. 
Let's install the ``simplejson`` package as a test::

    $ pip install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Downloading/unpacking simplejson
      Cannot fetch index base URL http://localhost:3141/root/pypi/+simple/
      Could not find any downloads that satisfy the requirement simplejson
    Cleaning up...
    No distributions at all found for simplejson
    Storing complete log in /home/hpk/.pip/pip.log

Let's uninstall it::

    $ pip uninstall -y simplejson
    Cannot uninstall requirement simplejson, not installed
    Storing complete log in /home/hpk/.pip/pip.log

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    Best match: simplejson 3.3.0
    Downloading http://localhost:3141/root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz#md5=0e29b393bceac8081fa4e93ff9f6a001
    Processing simplejson-3.3.0.tar.gz
    Writing /tmp/easy_install-uscj2Y/simplejson-3.3.0/setup.cfg
    Running simplejson-3.3.0/setup.py -q bdist_egg --dist-dir /tmp/easy_install-uscj2Y/simplejson-3.3.0/egg-dist-tmp-kN86zD
    zip_safe flag not set; analyzing archive contents...
    simplejson.tests.__init__: module references __file__
    Adding simplejson 3.3.0 to easy-install.pth file
    
    Installed /home/hpk/p/devpi/doc/docenv/lib/python2.7/site-packages/simplejson-3.3.0-py2.7-linux-x86_64.egg
    Processing dependencies for simplejson
    Finished processing dependencies for simplejson

Feel free to install any other package.  If you encounter lookup/download
issues when installing a package, please report the offending
package name to the `devpi issue tracker`_, at best including
the output of ``devpi-server --log``.  We aim to get the
mirroring 100% bug free and compatible to pypi.python.org.

.. _perminstallindex:

permanent index server configuration for pip
+++++++++++++++++++++++++++++++++++++++++++++++++++++

To avoid having to re-type index URLs, you can configure pip by
setting the index-url entry in your ``$HOME/.pip/pip.conf`` (posix) or 
``$HOME/pip/pip.conf`` (windows).  Let's do it for the ``root/pypi``
index::
    
    # content of pip.conf
    [global]
    index-url = http://localhost:3141/root/pypi/+simple/

Alternatively, you can add a special environment variable
to your shell settings (e.g. ``.bashrc``):

   export PIP_INDEX_URL=http://localhost:3141/root/pypi/+simple/


permanent easy_install configuration
+++++++++++++++++++++++++++++++++++++++++++++++++

You can configure ``easy_install`` by an entry in 
the ``$HOME/.pydistutils.cfg`` file::
    
    # content of .pydistutils.cfg
    [easy_install]
    index_url = http://localhost:3141/root/pypi/+simple/


Checking and stopping the background server
++++++++++++++++++++++++++++++++++++++++++++

At any time you can check the background server status with::

    $ devpi-server --status
    no server is running

Or stop it::
    
    $ devpi-server --stop
    no server found

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    last lines of devpi-server log
    2013-08-14 16:01:09,668 [INFO ] devpi_server.extpypi: changelog/update tasks starting
    2013-08-14 16:01:09,673 [INFO ] devpi_server.extpypi: detected MIRRORVERSION CHANGE, restarting caching info
    2013-08-14 16:01:09,674 [INFO ] devpi_server.extpypi: retrieving initial name/serial list
    2013-08-14 16:01:09,741 [INFO ] devpi_server.db: setting password for user 'root'
    2013-08-14 16:01:09,741 [INFO ] devpi_server.db: created user 'root' with email None
    2013-08-14 16:01:09,742 [INFO ] devpi_server.db: created index root/pypi: {'uploadtrigger_jenkins': None, 'acl_upload': ['root'], 'bases': (), 'volatile': False, 'type': 'mirror'}
    2013-08-14 16:01:09,743 [INFO ] devpi_server.db: created index root/dev: {'uploadtrigger_jenkins': None, 'acl_upload': ['root'], 'bases': ('root/pypi',), 'volatile': True, 'type': 'stage'}
    2013-08-14 16:01:09,770 [INFO ] devpi_server.main: devpi-server version: 1.0rc2
    2013-08-14 16:01:09,770 [INFO ] devpi_server.main: serverdir: /home/hpk/p/devpi/doc/.devpi/server
    2013-08-14 16:01:09,770 [INFO ] devpi_server.main: serving at url: http://localhost:3141
    2013-08-14 16:01:09,770 [INFO ] devpi_server.main: bug tracker: https://bitbucket.org/hpk42/devpi/issues
    2013-08-14 16:01:09,770 [INFO ] devpi_server.main: IRC: #pylib on irc.freenode.net
    2013-08-14 16:01:09,782 [INFO ] devpi_server.main: bottleserver type: eventlet
    Bottle v0.11.6 server starting up (using EventletServer())...
    Listening on http://localhost:3141/
    Hit Ctrl-C to quit.
    
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi-server", line 9, in <module>
        load_entry_point('devpi-server==1.0rc2', 'console_scripts', 'devpi-server')()
      File "/home/hpk/p/devpi/server/devpi_server/main.py", line 58, in main
        return bottle_run(xom)
      File "/home/hpk/p/devpi/server/devpi_server/main.py", line 83, in bottle_run
        reloader=False, port=port)
      File "/home/hpk/venv/0/bin/bottle.py", line 2703, in run
        server.run(app)
      File "/home/hpk/venv/0/bin/bottle.py", line 2528, in run
        wsgi.server(listen((self.host, self.port)), handler,
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/eventlet/convenience.py", line 38, in listen
        sock.bind(addr)
      File "/usr/lib/python2.7/socket.py", line 224, in meth
        return getattr(self._sock,name)(*args)
    socket.error: [Errno 98] Address already in use
    logfile at: /home/hpk/p/devpi/doc/.devpi/server/.xproc/devpi-server/xprocess.log
