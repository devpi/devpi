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
    1.2.1

start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::
    
    $ devpi-server --start
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=11864
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

You now have a server listning on ``http://localhost:3141``.

.. _`install_first`:

install your first package with pip/easy_install
+++++++++++++++++++++++++++++++++++++++++++++++++++++

Both pip_ and easy_install_ support the ``-i`` option to specify
an index server url.  We use it to point installers to a special
``root/pypi`` index, served by ``devpi-server`` by default. 
Let's install the ``simplejson`` package as a test from our cache::

    $ pip install -i http://localhost:3141/root/pypi/ simplejson
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
    Best match: simplejson 3.3.1
    Downloading http://localhost:3141/root/pypi/+f/36eec59b63bb852eaaac724ac8985f74/simplejson-3.3.1.tar.gz#md5=36eec59b63bb852eaaac724ac8985f74
    Processing simplejson-3.3.1.tar.gz
    Writing /tmp/easy_install-6J9pUa/simplejson-3.3.1/setup.cfg
    Running simplejson-3.3.1/setup.py -q bdist_egg --dist-dir /tmp/easy_install-6J9pUa/simplejson-3.3.1/egg-dist-tmp-bNng_F
    zip_safe flag not set; analyzing archive contents...
    simplejson.tests.__init__: module references __file__
    Adding simplejson 3.3.1 to easy-install.pth file
    
    Installed /tmp/docenv/lib/python2.7/site-packages/simplejson-3.3.1-py2.7-linux-x86_64.egg
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
``$HOME/pip/pip.ini`` (windows).  Let's do it for the ``root/pypi``
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
    server is running with pid 11864

Or stop it::
    
    $ devpi-server --stop
    killed server pid=11864

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    last lines of devpi-server log
    2013-11-18 14:22:32,761 [INFO ] requests.packages.urllib3.connectionpool: Starting new HTTPS connection (1): pypi.python.org
    2013-11-18 14:22:53,440 [INFO ] devpi_server.extpypi: changelog/update tasks starting
    2013-11-18 14:22:53,444 [INFO ] devpi_server.db: setting password for user u'root'
    2013-11-18 14:22:53,444 [INFO ] devpi_server.db: created user u'root' with email None
    2013-11-18 14:22:53,444 [INFO ] devpi_server.db: created index root/pypi: {u'volatile': False, u'acl_upload': [u'root'], u'bases': (), u'type': u'mirror', u'uploadtrigger_jenkins': None}
    2013-11-18 14:22:53,485 [INFO ] devpi_server.main: devpi-server version: 1.2.1
    2013-11-18 14:22:53,485 [INFO ] devpi_server.main: serverdir: /tmp/home/.devpi/server
    2013-11-18 14:22:53,485 [INFO ] devpi_server.main: serving at url: http://localhost:3141
    2013-11-18 14:22:53,485 [INFO ] devpi_server.main: bug tracker: https://bitbucket.org/hpk42/devpi/issues
    2013-11-18 14:22:53,485 [INFO ] devpi_server.main: IRC: #devpi on irc.freenode.net
    2013-11-18 14:22:53,547 [INFO ] devpi_server.main: bottleserver type: eventlet
    Bottle v0.11.6 server starting up (using EventletServer())...
    Listening on http://localhost:3141/
    Hit Ctrl-C to quit.
    
    (11864) wsgi starting up on http://127.0.0.1:3141/
    (11864) accepted ('127.0.0.1', 48440)
    127.0.0.1 - - [18/Nov/2013 14:22:53] "GET / HTTP/1.1" 200 500 0.000663
    (11864) accepted ('127.0.0.1', 48441)
    127.0.0.1 - - [18/Nov/2013 14:22:53] "GET /root/pypi/simplejson/ HTTP/1.1" 302 200 0.001444
    (11864) accepted ('127.0.0.1', 48442)
    2013-11-18 14:22:53,784 [INFO ] requests.packages.urllib3.connectionpool: Starting new HTTPS connection (1): pypi.python.org
    127.0.0.1 - - [18/Nov/2013 14:22:54] "GET /root/pypi/+simple/simplejson/ HTTP/1.1" 200 15054 0.268671
    (11864) accepted ('127.0.0.1', 48445)
    2013-11-18 14:22:54,148 [INFO ] devpi_server.filestore: cache-streaming: https://pypi.python.org/packages/source/s/simplejson/simplejson-3.3.1.tar.gz, target root/pypi/+f/36eec59b63bb852eaaac724ac8985f74/simplejson-3.3.1.tar.gz
    2013-11-18 14:22:54,148 [INFO ] devpi_server.filestore: starting file iteration: root/pypi/+f/36eec59b63bb852eaaac724ac8985f74/simplejson-3.3.1.tar.gz (size 67371)
    2013-11-18 14:22:54,221 [INFO ] devpi_server.filestore: finished getting remote u'https://pypi.python.org/packages/source/s/simplejson/simplejson-3.3.1.tar.gz'
    127.0.0.1 - - [18/Nov/2013 14:22:54] "GET /root/pypi/+f/36eec59b63bb852eaaac724ac8985f74/simplejson-3.3.1.tar.gz HTTP/1.1" 200 67503 0.096431
    (11864) accepted ('127.0.0.1', 48456)
    127.0.0.1 - - [18/Nov/2013 14:22:56] "GET /root/pypi/+simple/simplejson/ HTTP/1.1" 200 15054 0.025500
    (11864) accepted ('127.0.0.1', 48457)
    2013-11-18 14:22:56,302 [INFO ] devpi_server.filestore: starting file iteration: root/pypi/+f/36eec59b63bb852eaaac724ac8985f74/simplejson-3.3.1.tar.gz (size 67371)
    127.0.0.1 - - [18/Nov/2013 14:22:56] "GET /root/pypi/+f/36eec59b63bb852eaaac724ac8985f74/simplejson-3.3.1.tar.gz HTTP/1.1" 200 67503 0.001415
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
