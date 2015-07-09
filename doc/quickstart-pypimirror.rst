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
    2.2.2

.. note::

    This tutorial does not require you to install or use the ``devpi-client``
    package.  Consult :doc:`quickstart-releaseprocess` to learn more 
    about how you can use the ``devpi`` command line tool to
    manage working with uploads, tests and multiple indexes.


start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::
    
    $ devpi-server --start
    2015-07-09 13:30:45,278 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-07-09 13:30:45,279 INFO  NOCTX generated uuid: 92e181789c9f42e99248d7e9c4a3dac1
    2015-07-09 13:30:45,279 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-07-09 13:30:45,279 INFO  NOCTX DB: Creating schema
    2015-07-09 13:30:45,322 INFO  [Wtx-1] setting password for user u'root'
    2015-07-09 13:30:45,322 INFO  [Wtx-1] created user u'root' with email None
    2015-07-09 13:30:45,322 INFO  [Wtx-1] created root user
    2015-07-09 13:30:45,322 INFO  [Wtx-1] created root/pypi index
    2015-07-09 13:30:45,335 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=14022
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
    You are using pip version 6.1.1, however version 7.1.0 is available.
    You should consider upgrading via the 'pip install --upgrade pip' command.
    Collecting simplejson
      Downloading http://localhost:3141/root/pypi/+f/117/346e5ee4ed443/simplejson-3.7.3.tar.gz (74kB)
    Installing collected packages: simplejson
      Running setup.py install for simplejson
    Successfully installed simplejson-3.7.3

Let's uninstall it::

    $ pip uninstall -y simplejson
    You are using pip version 6.1.1, however version 7.1.0 is available.
    You should consider upgrading via the 'pip install --upgrade pip' command.
    Uninstalling simplejson-3.7.3:
      Successfully uninstalled simplejson-3.7.3

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    Best match: simplejson 3.7.3
    Downloading http://localhost:3141/root/pypi/+f/117/346e5ee4ed443/simplejson-3.7.3.tar.gz#md5=117346e5ee4ed4434ffe485f8e58f5ed
    Processing simplejson-3.7.3.tar.gz
    Writing /tmp/easy_install-TT3AO7/simplejson-3.7.3/setup.cfg
    Running simplejson-3.7.3/setup.py -q bdist_egg --dist-dir /tmp/easy_install-TT3AO7/simplejson-3.7.3/egg-dist-tmp-EjdsTN
    zip_safe flag not set; analyzing archive contents...
    simplejson.tests.__init__: module references __file__
    creating /tmp/docenv/lib/python2.7/site-packages/simplejson-3.7.3-py2.7-linux-x86_64.egg
    Extracting simplejson-3.7.3-py2.7-linux-x86_64.egg to /tmp/docenv/lib/python2.7/site-packages
    Adding simplejson 3.7.3 to easy-install.pth file
    
    Installed /tmp/docenv/lib/python2.7/site-packages/simplejson-3.7.3-py2.7-linux-x86_64.egg
    Processing dependencies for simplejson
    Finished processing dependencies for simplejson

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
    2015-07-09 13:30:58,692 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-07-09 13:30:58,692 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    server is running with pid 14022

Or stop it::
    
    $ devpi-server --stop
    2015-07-09 13:30:59,323 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-07-09 13:30:59,324 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=14022

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    2015-07-09 13:30:59,945 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-07-09 13:30:59,946 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    last lines of devpi-server log
    2015-07-09 13:30:53,953 INFO  [req3] GET /root/pypi/simplejson/
    2015-07-09 13:30:53,964 INFO  [req4] GET /root/pypi/+simple/simplejson
    2015-07-09 13:30:54,034 INFO  [req5] GET /root/pypi/+f/117/346e5ee4ed443/simplejson-3.7.3.tar.gz
    2015-07-09 13:30:54,126 INFO  [req5] [Wtx2] reading remote: https://pypi.python.org/packages/source/s/simplejson/simplejson-3.7.3.tar.gz, target root/pypi/+f/117/346e5ee4ed443/simplejson-3.7.3.tar.gz
    2015-07-09 13:30:54,262 INFO  [req5] [Wtx2] fswriter3: committed: keys: u'root/pypi/+f/117/346e5ee4ed443/simplejson-3.7.3.tar.gz', files_commit: +files/root/pypi/+f/117/346e5ee4ed443/simplejson-3.7.3.tar.gz
    2015-07-09 13:30:56,681 INFO  [req6] GET /root/pypi/+simple/simplejson/
    2015-07-09 13:30:56,838 INFO  [req7] GET /root/pypi/+f/117/346e5ee4ed443/simplejson-3.7.3.tar.gz
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
