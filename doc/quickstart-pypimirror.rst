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
    2.5.0

.. note::

    This tutorial does not require you to install or use the ``devpi-client``
    package.  Consult :doc:`quickstart-releaseprocess` to learn more 
    about how you can use the ``devpi`` command line tool to
    manage working with uploads, tests and multiple indexes.


start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background issue::
    
    $ devpi-server --start
    2015-11-19 16:24:49,240 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-11-19 16:24:49,240 INFO  NOCTX generated uuid: 32750abd37e14877b047c38cde93c823
    2015-11-19 16:24:49,240 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-11-19 16:24:49,241 INFO  NOCTX DB: Creating schema
    2015-11-19 16:24:49,268 INFO  [Wtx-1] setting password for user u'root'
    2015-11-19 16:24:49,268 INFO  [Wtx-1] created user u'root' with email None
    2015-11-19 16:24:49,268 INFO  [Wtx-1] created root user
    2015-11-19 16:24:49,268 INFO  [Wtx-1] created root/pypi index
    2015-11-19 16:24:49,279 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=11247
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
      Downloading http://localhost:3141/root/pypi/+f/b84/41f1053edd9dc/simplejson-3.8.1.tar.gz (76kB)
    Building wheels for collected packages: simplejson
      Running setup.py bdist_wheel for simplejson
      Stored in directory: /tmp/home/.cache/pip/wheels/49/4a/75/dc2813f3d3f9e3b87f153fb0e2968ba8d4917b9ace04d5fec8
    Successfully built simplejson
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
    Writing /tmp/easy_install-nVLvli/simplejson-3.8.1/setup.cfg
    Running simplejson-3.8.1/setup.py -q bdist_egg --dist-dir /tmp/easy_install-nVLvli/simplejson-3.8.1/egg-dist-tmp-ClJku4
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
    2015-11-19 16:25:02,500 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-11-19 16:25:02,500 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    server is running with pid 11247

Or stop it::
    
    $ devpi-server --stop
    2015-11-19 16:25:03,124 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-11-19 16:25:03,124 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=11247

Finally, you can also look at the logfile of the background server
(also after it has been stopped)::

    $ devpi-server --log
    2015-11-19 16:25:03,685 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-11-19 16:25:03,686 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    last lines of devpi-server log
    2015-11-19 16:24:56,790 INFO  [req3] GET /root/pypi/simplejson/
    2015-11-19 16:24:56,796 INFO  [req4] GET /root/pypi/+simple/simplejson
    2015-11-19 16:24:56,861 INFO  [req5] GET /root/pypi/+f/b84/41f1053edd9dc/simplejson-3.8.1.tar.gz
    2015-11-19 16:24:57,117 INFO  [req5] [Wtx2] reading remote: https://pypi.python.org/packages/source/s/simplejson/simplejson-3.8.1.tar.gz, target root/pypi/+f/b84/41f1053edd9dc/simplejson-3.8.1.tar.gz
    2015-11-19 16:24:57,274 INFO  [req5] [Wtx2] fswriter3: committed: keys: u'root/pypi/+f/b84/41f1053edd9dc/simplejson-3.8.1.tar.gz', files_commit: +files/root/pypi/+f/b84/41f1053edd9dc/simplejson-3.8.1.tar.gz
    2015-11-19 16:25:00,445 INFO  [req6] GET /root/pypi/+simple/simplejson/
    2015-11-19 16:25:00,623 INFO  [req7] GET /root/pypi/+f/b84/41f1053edd9dc/simplejson-3.8.1.tar.gz
    logfile at: /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.
