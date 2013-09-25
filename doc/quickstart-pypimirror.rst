
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
    set root/pypi default index
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process 'devpi-server' started pid=1063
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

You now have a server listning on ``http://localhost:3141``.

.. note::

    If you have ``eventlet`` installed, ``devpi-server``
    will automatically pick the eventlet-wsgi server,
    see the ``--bottleserver`` option.

.. _`install_first`:

install your first package with pip/easy_install
+++++++++++++++++++++++++++++++++++++++++++++++++++++

Both pip_ and easy_install_ support the ``-i`` option to specify
an index server url.  We use it to point installers to a special
``root/pypi`` index, served by ``devpi-server`` by default. 
Let's install the ``simplejson`` package as a test::

    $ pip install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Downloading/unpacking simplejson
      Running setup.py egg_info for package simplejson
        
    Installing collected packages: simplejson
      Running setup.py install for simplejson
        building 'simplejson._speedups' extension
        gcc -pthread -fno-strict-aliasing -DNDEBUG -g -fwrapv -O2 -Wall -Wstrict-prototypes -fPIC -I/usr/include/python2.7 -c simplejson/_speedups.c -o build/temp.linux-x86_64-2.7/simplejson/_speedups.o
        gcc -pthread -shared -Wl,-O1 -Wl,-Bsymbolic-functions -Wl,-Bsymbolic-functions -Wl,-z,relro build/temp.linux-x86_64-2.7/simplejson/_speedups.o -o build/lib.linux-x86_64-2.7/simplejson/_speedups.so
        
    Successfully installed simplejson
    Cleaning up...

Let's uninstall it::

    $ pip uninstall -y simplejson
    Uninstalling simplejson:
      Successfully uninstalled simplejson

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    Best match: simplejson 3.3.0
    Downloading http://localhost:3141/root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz#md5=0e29b393bceac8081fa4e93ff9f6a001
    Processing simplejson-3.3.0.tar.gz
    Writing /tmp/easy_install-u_vGqI/simplejson-3.3.0/setup.cfg
    Running simplejson-3.3.0/setup.py -q bdist_egg --dist-dir /tmp/easy_install-u_vGqI/simplejson-3.3.0/egg-dist-tmp-qt_HB_
    zip_safe flag not set; analyzing archive contents...
    simplejson.tests.__init__: module references __file__
    Adding simplejson 3.3.0 to easy-install.pth file
    
    Installed /tmp/docenv/lib/python2.7/site-packages/simplejson-3.3.0-py2.7-linux-x86_64.egg
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
    
    # $HOME/.pip/pip.conf
    [global]
    index-url = http://localhost:3141/root/pypi/+simple/

Alternatively, you can add a special environment variable
to your shell settings (e.g. ``.bashrc``):

   export PIP_INDEX_URL=http://localhost:3141/root/pypi/+simple/


permanent easy_install configuration
+++++++++++++++++++++++++++++++++++++++++++++++++

You can configure ``easy_install`` by an entry in 
the ``$HOME/.pydistutils.cfg`` file::
    
    # $HOME/.pydistutils.cfg:
    [easy_install]
    index_url = http://localhost:3141/root/pypi/+simple/


Checking and stopping the background server
++++++++++++++++++++++++++++++++++++++++++++

At any time you can check the background server status with::

    $ devpi-server --status
    server is running with pid 1063

Or stop it::
    
    $ devpi-server --stop
    killed server pid=1063

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    last lines of devpi-server log
    2013-09-25 16:03:58,096 [INFO ] devpi_server.extpypi: changelog/update tasks starting
    2013-09-25 16:03:58,122 [INFO ] devpi_server.main: devpi-server version: 1.1
    2013-09-25 16:03:58,122 [INFO ] devpi_server.main: serverdir: /tmp/home/.devpi/server
    2013-09-25 16:03:58,122 [INFO ] devpi_server.main: serving at url: http://localhost:3141
    2013-09-25 16:03:58,122 [INFO ] devpi_server.main: bug tracker: https://bitbucket.org/hpk42/devpi/issues
    2013-09-25 16:03:58,122 [INFO ] devpi_server.main: IRC: #devpi on irc.freenode.net
    2013-09-25 16:03:58,133 [INFO ] devpi_server.main: bottleserver type: eventlet
    Bottle v0.11.6 server starting up (using EventletServer())...
    Listening on http://localhost:3141/
    Hit Ctrl-C to quit.
    
    (1063) wsgi starting up on http://127.0.0.1:3141/
    (1063) accepted ('127.0.0.1', 52691)
    127.0.0.1 - - [25/Sep/2013 16:03:58] "GET / HTTP/1.1" 200 498 0.000579
    (1063) accepted ('127.0.0.1', 52692)
    2013-09-25 16:03:58,358 [INFO ] requests.packages.urllib3.connectionpool: Starting new HTTPS connection (1): pypi.python.org
    127.0.0.1 - - [25/Sep/2013 16:03:58] "GET /root/pypi/+simple/simplejson/ HTTP/1.1" 200 16697 0.259157
    (1063) accepted ('127.0.0.1', 52694)
    2013-09-25 16:03:58,696 [INFO ] devpi_server.filestore: cache-streaming: https://pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz, target root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz
    2013-09-25 16:03:58,696 [INFO ] devpi_server.filestore: starting file iteration: root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz (size 67250)
    2013-09-25 16:03:58,801 [INFO ] devpi_server.filestore: finished getting remote 'https://pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz'
    127.0.0.1 - - [25/Sep/2013 16:03:58] "GET /root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz HTTP/1.1" 200 67382 0.137262
    (1063) accepted ('127.0.0.1', 52695)
    127.0.0.1 - - [25/Sep/2013 16:03:59] "GET /root/pypi/+simple/simplejson/ HTTP/1.1" 200 16697 0.014801
    (1063) accepted ('127.0.0.1', 52696)
    2013-09-25 16:04:00,004 [INFO ] devpi_server.filestore: starting file iteration: root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz (size 67250)
    127.0.0.1 - - [25/Sep/2013 16:04:00] "GET /root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz HTTP/1.1" 200 67382 0.001008
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
