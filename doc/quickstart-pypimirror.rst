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
    5.0.0

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
    2018-01-17 15:40:11,375 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2018-01-17 15:40:11,375 INFO  NOCTX generated uuid: cf25cfb22d2b4487a9ab4c1e527e5679
    2018-01-17 15:40:11,376 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2018-01-17 15:40:11,384 INFO  NOCTX DB: Creating schema
    2018-01-17 15:40:11,391 INFO  [Wtx-1] setting password for user 'root'
    2018-01-17 15:40:11,392 INFO  [Wtx-1] created user 'root' with email None
    2018-01-17 15:40:11,392 INFO  [Wtx-1] created root user
    2018-01-17 15:40:11,392 INFO  [Wtx-1] created root/pypi index
    2018-01-17 15:40:11,395 INFO  [Wtx-1] fswriter0: committed: keys: 'root/.config','.config'


start background devpi-server process
++++++++++++++++++++++++++++++++++++++++++++++

To start ``devpi-server`` in the background we use supervisor as an example.
First we create the config file for it::

    $ devpi-server --gen-config
    It is highly recommended to use a configuration file for devpi-server, see --configfile option.
    wrote gen-config/crontab
    wrote gen-config/net.devpi.plist
    wrote gen-config/launchd-macos.txt
    wrote gen-config/nginx-devpi.conf
    wrote gen-config/supervisor-devpi.conf
    wrote gen-config/devpi.service
    wrote gen-config/windows-service.txt

Then we start supervisord using a config which includes the generated file,
see :ref:`quickstart-server` for more details::

    $ supervisord -c gen-config/supervisord.conf

..
    $ sleep 3

You now have a server listening on ``http://localhost:3141``.

.. _`install_first`:

install your first package with pip/easy_install
+++++++++++++++++++++++++++++++++++++++++++++++++++++

Both pip_ and easy_install_ support the ``-i`` option to specify
an index server url.  We use it to point installers to a special
``root/pypi`` index, served by ``devpi-server`` by default.
Let's install the ``simplejson`` package as a test from our cache::

    $ pip install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Looking in indexes: http://localhost:3141/root/pypi/+simple/
    Collecting simplejson
      Downloading http://localhost:3141/root/pypi/+f/870/bf6257465ce2e/simplejson-3.13.2.tar.gz (79kB)
    Building wheels for collected packages: simplejson
      Running setup.py bdist_wheel for simplejson: started
      Running setup.py bdist_wheel for simplejson: finished with status 'done'
      Stored in directory: /tmp/home/Library/Caches/pip/wheels/98/f9/e6/265acfaccc6c6da33438bb7aa510a7baa504df78438fde3f9e
    Successfully built simplejson
    Installing collected packages: simplejson
    Successfully installed simplejson-3.13.2

Let's uninstall it::

    $ pip uninstall -y simplejson
    Uninstalling simplejson-3.13.2:
      Successfully uninstalled simplejson-3.13.2

and then re-install it with ``easy_install``::

    $ easy_install -i http://localhost:3141/root/pypi/+simple/ simplejson
    Searching for simplejson
    Reading http://localhost:3141/root/pypi/+simple/simplejson/
    Downloading http://localhost:3141/root/pypi/+f/870/bf6257465ce2e/simplejson-3.13.2.tar.gz#md5=870bf6257465ce2ee8cad14e2394f7eb
    Best match: simplejson 3.13.2
    Processing simplejson-3.13.2.tar.gz
    Writing /tmp/easy_install-9p4zdv87/simplejson-3.13.2/setup.cfg
    Running simplejson-3.13.2/setup.py -q bdist_egg --dist-dir /tmp/easy_install-9p4zdv87/simplejson-3.13.2/egg-dist-tmp-2hrrabuf
    zip_safe flag not set; analyzing archive contents...
    simplejson.__pycache__._speedups.cpython-34: module references __file__
    simplejson.tests.__pycache__.__init__.cpython-34: module references __file__
    creating /private/tmp/docenv/lib/python3.4/site-packages/simplejson-3.13.2-py3.4-macosx-10.12-x86_64.egg
    Extracting simplejson-3.13.2-py3.4-macosx-10.12-x86_64.egg to /private/tmp/docenv/lib/python3.4/site-packages
    Adding simplejson 3.13.2 to easy-install.pth file
    
    Installed /private/tmp/docenv/lib/python3.4/site-packages/simplejson-3.13.2-py3.4-macosx-10.12-x86_64.egg
    Processing dependencies for simplejson
    Finished processing dependencies for simplejson

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

and then recreate the search index::

    $ devpi-server --recreate-search-index --offline
    2018-01-17 15:40:52,780 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2018-01-17 15:40:52,781 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2018-01-17 15:40:52,804 INFO  [Rtx3] Search-Indexing root/pypi:
    2018-01-17 15:41:18,898 INFO  [Wtx3] setting projects cache for 'simplejson'
    2018-01-17 15:42:23,387 INFO  [Wtx3] Committing 126895 new documents to search index.
    2018-01-17 15:56:25,687 INFO  [Wtx3] Finished committing 126895 documents to search index.
    2018-01-17 15:56:25,760 INFO  [Wtx3] fswriter4: committed: keys: 'root/pypi/+f/870/bf6257465ce2e/simplejson-3.13.2.tar.gz'

and then start the server again::

    $ supervisorctl -c gen-config/supervisord.conf start devpi-server
    devpi-server: started

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
