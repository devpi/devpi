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
    6.9.2

.. note::

    This tutorial does not require you to install or use the ``devpi-client``
    package.  Consult :doc:`quickstart-releaseprocess` to learn more
    about how you can use the ``devpi`` command line tool to
    manage working with uploads, tests and multiple indexes.


Initialize devpi-server
+++++++++++++++++++++++

..
    $ rm -rf ~/.devpi/server

To initialize ``devpi-server`` issue::

    $ devpi-init
    INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    INFO  NOCTX generated uuid: 446e22e0db5e41a5989fd671e98ec30b
    INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    INFO  NOCTX DB: Creating schema
    INFO  [Wtx-1] setting password for user 'root'
    INFO  [Wtx-1] created user 'root'
    INFO  [Wtx-1] created root user
    INFO  [Wtx-1] created root/pypi index
    INFO  [Wtx-1] fswriter0: committed at 0

start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background we use supervisor as an example.
First we create the config file for it::

    $ devpi-gen-config
    It is highly recommended to use a configuration file for devpi-server, see --configfile option.
    wrote gen-config/crontab
    wrote gen-config/net.devpi.plist
    wrote gen-config/launchd-macos.txt
    wrote gen-config/nginx-devpi.conf
    wrote gen-config/nginx-devpi-caching.conf
    wrote gen-config/supervisor-devpi.conf
    wrote gen-config/supervisord.conf
    wrote gen-config/devpi.service
    wrote gen-config/windows-service.txt

Then we start supervisord using a config which includes the generated file,
see :ref:`quickstart-server` for more details::

    $ supervisord -c gen-config/supervisord.conf

..
    $ waitforports -t 60 3141
    Waiting for 127.0.0.1:3141

You now have a server listening on ``http://localhost:3141``.

.. _`install_first`:

install your first package with pip/easy_install
+++++++++++++++++++++++++++++++++++++++++++++++++++++

Both pip_ and easy_install_ support the ``-i`` option to specify
an index server url.  We use it to point installers to a special
``root/pypi`` index, served by ``devpi-server`` by default.
Let's install the ``pg8000`` package as a test from our cache::

    $ pip install -i http://localhost:3141/root/pypi/+simple/ pg8000==1.30.2
    Looking in indexes: http://localhost:3141/root/pypi/+simple/
    Collecting pg8000==1.30.2
      Downloading http://localhost:3141/root/pypi/%2Bf/2fc/6bf2d81d70255/pg8000-1.30.2-py3-none-any.whl (54 kB)
    Collecting scramp>=1.4.4 (from pg8000==1.30.2)
      Downloading http://localhost:3141/root/pypi/%2Bf/b14/2312df7c29772/scramp-1.4.4-py3-none-any.whl (13 kB)
    Collecting python-dateutil>=2.8.2 (from pg8000==1.30.2)
      Downloading http://localhost:3141/root/pypi/%2Bf/961/d03dc3453ebbc/python_dateutil-2.8.2-py2.py3-none-any.whl (247 kB)
    Collecting six>=1.5 (from python-dateutil>=2.8.2->pg8000==1.30.2)
      Downloading http://localhost:3141/root/pypi/%2Bf/8ab/b2f1d86890a2d/six-1.16.0-py2.py3-none-any.whl (11 kB)
    Collecting asn1crypto>=1.5.1 (from scramp>=1.4.4->pg8000==1.30.2)
      Downloading http://localhost:3141/root/pypi/%2Bf/db4/e40728b728508/asn1crypto-1.5.1-py2.py3-none-any.whl (105 kB)
    Installing collected packages: asn1crypto, six, scramp, python-dateutil, pg8000
    Successfully installed asn1crypto-1.5.1 pg8000-1.30.2 python-dateutil-2.8.2 scramp-1.4.4 six-1.16.0

Feel free to install any other package.  If you encounter lookup/download
issues when installing a public pypi package, please report the offending
package name to the `devpi issue tracker`_, at best including
the output of ``devpi-server --log``.  We constantly aim to get the
mirroring 100% bug free and compatible to pypi.org.

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

We now need to stop the server, we do that using supervisorctl::

    $ supervisorctl -c gen-config/supervisord.conf stop devpi-server
    devpi-server: stopped

and then start the server again::

    $ supervisorctl -c gen-config/supervisord.conf start devpi-server
    devpi-server: started

..
    $ sleep 10

We can now use search with pip::

    $ pip search --index http://localhost:3141/root/pypi/ devpi-client
    devpi-client-extensions ()  - [root/pypi]
    devpi-client ()             - [root/pypi]

.. note::

   Currently devpi-web does not support showing the description of pypi.org packages
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


running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to learn more.

Now shutdown supervisord which was started at the beginning of this tutorial::

    $ supervisorctl -c gen-config/supervisord.conf shutdown
    Shut down
