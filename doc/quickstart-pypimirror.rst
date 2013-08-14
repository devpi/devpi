
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
    process 'devpi-server' started pid=13277
    devpi-server process startup detected
    logfile is at /home/hpk/p/devpi/doc/.devpi/server/.xproc/devpi-server/xprocess.log

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
    Writing /tmp/easy_install-Ur2D_K/simplejson-3.3.0/setup.cfg
    Running simplejson-3.3.0/setup.py -q bdist_egg --dist-dir /tmp/easy_install-Ur2D_K/simplejson-3.3.0/egg-dist-tmp-ulhCpJ
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
    server is running with pid 13277

Or stop it::
    
    $ devpi-server --stop
    killed server pid=13277

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    last lines of devpi-server log
    2013-08-14 17:42:23,857 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-1.5.tar.gz
    2013-08-14 17:42:23,857 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/2.4/s/simplejson/simplejson-1.5-py2.4.egg
    2013-08-14 17:42:23,858 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/2.4/s/simplejson/simplejson-1.4-py2.4.egg
    2013-08-14 17:42:23,858 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-1.4.tar.gz
    2013-08-14 17:42:23,859 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-1.3.tar.gz
    2013-08-14 17:42:23,859 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/2.4/s/simplejson/simplejson-1.3-py2.4.egg
    2013-08-14 17:42:23,859 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-1.1.tar.gz
    2013-08-14 17:42:23,860 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/2.4/s/simplejson/simplejson-1.1-py2.4.egg
    2013-08-14 17:42:23,860 [INFO ] devpi_server.filestore: replaced md5 info for root/pypi/f/https/pypi.python.org/packages/2.3/s/simplejson/simplejson-1.1-py2.3.egg
    127.0.0.1 - - [14/Aug/2013 17:42:23] "GET /root/pypi/+simple/simplejson/ HTTP/1.1" 200 16121 0.511770
    (13277) accepted ('127.0.0.1', 52968)
    2013-08-14 17:42:23,967 [INFO ] devpi_server.filestore: cache-streaming: https://pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz, target root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz
    2013-08-14 17:42:23,967 [INFO ] devpi_server.filestore: starting file iteration: root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz (size 67250)
    2013-08-14 17:42:24,126 [INFO ] devpi_server.filestore: finished getting remote 'https://pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz'
    127.0.0.1 - - [14/Aug/2013 17:42:24] "GET /root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz HTTP/1.1" 200 67382 0.199982
    (13277) accepted ('127.0.0.1', 52969)
    127.0.0.1 - - [14/Aug/2013 17:42:25] "GET /root/pypi/+simple/simplejson/ HTTP/1.1" 200 16121 0.020222
    (13277) accepted ('127.0.0.1', 52970)
    2013-08-14 17:42:25,547 [INFO ] devpi_server.filestore: starting file iteration: root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz (size 67250)
    127.0.0.1 - - [14/Aug/2013 17:42:25] "GET /root/pypi/f/https/pypi.python.org/packages/source/s/simplejson/simplejson-3.3.0.tar.gz HTTP/1.1" 200 67382 0.001728
    logfile at: /home/hpk/p/devpi/doc/.devpi/server/.xproc/devpi-server/xprocess.log
