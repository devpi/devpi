.. include:: links.rst

.. _quickstart-releaseprocess:

Quickstart: uploading, testing, pushing releases 
------------------------------------------------

This quickstart document walks you through setting up a self-contained
pypi release upload, testing and staging system for your Python packages.

Installing devpi client and server
++++++++++++++++++++++++++++++++++

We want to run the full devpi system on our laptop::

    pip install -U devpi-web devpi-client

Note that the ``devpi-web`` package will pull in the core
``devpi-server`` package.  If you don't want a web interface you 
can just install the latter only.

devpi quickstart: initializing basic scenario
+++++++++++++++++++++++++++++++++++++++++++++

The ``devpi quickstart`` command performs some basic initialization steps
on your local machine:

- start a background devpi-server at ``http://localhost:3141``

- configure the client-side tool ``devpi`` to connect to the newly
  started server

- create and login a user, using as defaults your current login name 
  and an empty password.

- create an index and directly use it.

Let's run the quickstart command which will trigger
a series of other devpi commands::

    $ devpi quickstart
    -->  /home/hpk/p/devpi/doc$ devpi-server --start 
    2015-11-11 14:43:04,877 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-11-11 14:43:04,877 INFO  NOCTX generated uuid: ac25f2228d464f88a53aea43195a91db
    2015-11-11 14:43:04,878 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-11-11 14:43:04,878 INFO  NOCTX DB: Creating schema
    2015-11-11 14:43:04,898 INFO  [Wtx-1] setting password for user u'root'
    2015-11-11 14:43:04,898 INFO  [Wtx-1] created user u'root' with email None
    2015-11-11 14:43:04,898 INFO  [Wtx-1] created root user
    2015-11-11 14:43:04,898 INFO  [Wtx-1] created root/pypi index
    2015-11-11 14:43:04,916 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=12830
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log
    -->  /home/hpk/p/devpi/doc$ devpi use http://localhost:3141 
    using server: http://localhost:3141/ (not logged in)
    no current index: type 'devpi use -l' to discover indices
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no
    
    -->  /home/hpk/p/devpi/doc$ devpi user -c testuser password= 
    user created: testuser
    
    -->  /home/hpk/p/devpi/doc$ devpi login testuser --password= 
    logged in 'testuser', credentials valid for 10.00 hours
    
    -->  /home/hpk/p/devpi/doc$ devpi index -c dev 
    http://localhost:3141/testuser/dev:
      type=stage
      bases=root/pypi
      volatile=True
      acl_upload=testuser
      pypi_whitelist=
    
    -->  /home/hpk/p/devpi/doc$ devpi use dev 
    current devpi index: http://localhost:3141/testuser/dev (logged in as testuser)
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no
    COMPLETED!  you can now work with your 'dev' index
      devpi install PKG   # install a pkg from pypi
      devpi upload        # upload a setup.py based project
      devpi test PKG      # download and test a tox-based project 
      devpi PUSH ...      # to copy releases between indexes
      devpi index ...     # to manipulate/create indexes
      devpi use ...       # to change current index
      devpi user ...      # to manipulate/create users
      devpi CMD -h        # help for a specific command
      devpi -h            # general help
    docs at http://doc.devpi.net

Show the version::

    $ devpi --version
    2.3.2

.. _`quickstart_release_steps`:

devpi install: installing a package
+++++++++++++++++++++++++++++++++++

We can now use the ``devpi`` command line client to trigger a ``pip
install`` of a pypi package using the index from our already running server::

    $ devpi install pytest
    -->  /home/hpk/p/devpi/doc$ /tmp/docenv/bin/pip install -U -i http://localhost:3141/testuser/dev/+simple/ pytest  [PIP_USE_WHEEL=1,PIP_PRE=1]
    Collecting pytest
      Downloading http://localhost:3141/root/pypi/+f/251/fe4ed8ed80855/pytest-2.8.2-py2.py3-none-any.whl (149kB)
    Requirement already up-to-date: py>=1.4.29 in /tmp/docenv/lib/python2.7/site-packages (from pytest)
    Installing collected packages: pytest
    Successfully installed pytest-2.8.2

The ``devpi install`` command configured a pip call, using the
pypi-compatible ``+simple/`` page on our ``testuser/dev`` index for
finding and downloading packages.  The ``pip`` executable was searched
in the ``PATH`` and found in ``docenv/bin/pip``.

Let's check that ``pytest`` was installed correctly::

    $ py.test --version
    This is pytest version 2.8.2, imported from /tmp/docenv/local/lib/python2.7/site-packages/pytest.pyc

You may invoke the ``devpi install`` command a second time which will
even work when you have no network.

.. _`devpi upload`:

devpi upload: uploading one or more packages
++++++++++++++++++++++++++++++++++++++++++++

We are going to use ``devpi`` command line tool facilities for 
performing uploads (you can also 
:ref:`use plain setup.py <configure pypirc>`).

Let's verify we are logged in to the correct index::

    $ devpi use
    current devpi index: http://localhost:3141/testuser/dev (logged in as testuser)
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no

Now go to the directory of a ``setup.py`` file of one of your projects  
(we assume it is named ``example``) to build and upload your package
to our ``testuser/dev`` index::

    example $ devpi upload
    using workdir /tmp/devpi0
    copied repo /home/hpk/p/devpi/.hg to /tmp/devpi0/upload/devpi/.hg
    pre-build: cleaning /home/hpk/p/devpi/doc/example/dist
    -->  /tmp/devpi0/upload/devpi/doc/example$ /tmp/docenv/bin/python setup.py sdist --formats gztar 
    built: /home/hpk/p/devpi/doc/example/dist/example-1.0.tar.gz [SDIST.TGZ] 0kb
    register example-1.0 to http://localhost:3141/testuser/dev/
    file_upload of example-1.0.tar.gz to http://localhost:3141/testuser/dev/

There are three triggered actions:

- detection of a mercurial repository, leading to copying all versioned
  files to a temporary work dir.  If you are not using mercurial,
  the copy-step is skipped and the upload operates directly on your source
  tree.

- registering the ``example`` release as defined in ``setup.py`` to 
  our current index

- building and uploading a ``gztar`` formatted release file from the
  workdir to the current index (using a ``setup.py`` invocation under
  the hood).

We can now install the freshly uploaded package::

    $ devpi install example
    -->  /home/hpk/p/devpi/doc$ /tmp/docenv/bin/pip install -U -i http://localhost:3141/testuser/dev/+simple/ example  [PIP_USE_WHEEL=1,PIP_PRE=1]
    Collecting example
      Downloading http://localhost:3141/testuser/dev/+f/b5f/237f371f39108/example-1.0.tar.gz
    Building wheels for collected packages: example
      Running setup.py bdist_wheel for example
      Stored in directory: /tmp/home/.cache/pip/wheels/5e/d2/8b/e681c48d694888af4453fa1b8d4c9145198377de0f3f171208
    Successfully built example
    Installing collected packages: example
    Successfully installed example-1.0

This installed your just uploaded package from the ``testuser/dev``
index where we previously uploaded the package.

.. note::

    ``devpi upload`` allows to simultanously upload multiple different 
    formats of your release files such as ``sdist.zip`` or ``bdist_egg``.
    The default is ``sdist.tgz``.



devpi test: testing an uploaded package
+++++++++++++++++++++++++++++++++++++++

If you have a package which uses tox_ for testing you may now invoke::

    $ devpi test example  # package needs to contain tox.ini
    received http://localhost:3141/testuser/dev/+f/b5f/237f371f39108/example-1.0.tar.gz
    unpacking /tmp/devpi-test0/downloads/example-1.0.tar.gz to /tmp/devpi-test0/targz
    /tmp/devpi-test0/targz/example-1.0$ tox --installpkg /tmp/devpi-test0/downloads/example-1.0.tar.gz -i ALL=http://localhost:3141/testuser/dev/+simple/ --recreate --result-json /tmp/devpi-test0/targz/toxreport.json -c /tmp/devpi-test0/targz/example-1.0/tox.ini
    python create: /tmp/devpi-test0/targz/example-1.0/.tox/python
    python installdeps: pytest
    python inst: /tmp/devpi-test0/downloads/example-1.0.tar.gz
    python installed: example==1.0,py==1.4.30,pytest==2.8.2,wheel==0.24.0
    python runtests: PYTHONHASHSEED='3374777198'
    python runtests: commands[0] | py.test
    ============================= test session starts ==============================
    platform linux2 -- Python 2.7.6, pytest-2.8.2, py-1.4.30, pluggy-0.3.1
    rootdir: /tmp/devpi-test0/targz/example-1.0, inifile: 
    collected 0 items
    
    ===============================  in 0.00 seconds ===============================
    ERROR: invocation failed (exit code 5), logfile: /tmp/devpi-test0/targz/example-1.0/.tox/python/log/python-3.log
    ERROR: actionid: python
    msg: runtests
    cmdargs: [local('/tmp/devpi-test0/targz/example-1.0/.tox/python/bin/py.test')]
    env: {'LANG': 'en_US.UTF-8', 'PIP_INDEX_URL': 'https://pypi.python.org/simple', 'VIRTUAL_ENV': '/tmp/devpi-test0/targz/example-1.0/.tox/python', 'PYTHONHASHSEED': '3374777198', 'PATH': '/tmp/devpi-test0/targz/example-1.0/.tox/python/bin:/tmp/docenv/bin:/home/hpk/bin:/home/hpk/venv/0/bin:/usr/local/bin:/home/hpk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games', 'TMPDIR': '/tmp'}
    
    ============================= test session starts ==============================
    platform linux2 -- Python 2.7.6, pytest-2.8.2, py-1.4.30, pluggy-0.3.1
    rootdir: /tmp/devpi-test0/targz/example-1.0, inifile: 
    collected 0 items
    
    ===============================  in 0.00 seconds ===============================
    
    ERROR: InvocationError: /tmp/devpi-test0/targz/example-1.0/.tox/python/bin/py.test (see /tmp/devpi-test0/targz/example-1.0/.tox/python/log/python-3.log)
    ___________________________________ summary ____________________________________
    ERROR:   python: commands failed
    wrote json report at: /tmp/devpi-test0/targz/toxreport.json
    posting tox result data to http://localhost:3141/testuser/dev/+f/b5f/237f371f39108/example-1.0.tar.gz
    successfully posted tox result data
    tox command failed 1

Here is what happened:

- devpi got the latest available version of ``example`` from the current
  index

- it unpacked it to a temp dir, found the ``tox.ini`` and then invoked
  tox, pointing it to our ``example-1.0.tar.gz``, forcing all installations
  to go through our current ``testuser/dev/+simple/`` index and instructing
  it to create a ``json`` report.

- after all tests ran, we send the ``toxreport.json`` to the devpi server
  where it will be attached precisely to our release file.
 
We can verify that the test status was recorded via::

    $ devpi list example
    http://localhost:3141/testuser/dev/+f/b5f/237f371f39108/example-1.0.tar.gz
    uwanda     linux2  python     2.7.6 tests failed

.. note::

    Since version 2.2.0 testing of universal wheels is supported if there
    also is an sdist which contains the neccessary tox.ini and tests files.
    Wheels typically don't contain them as they are a pure installation
    package.

devpi push: staging a release to another index
++++++++++++++++++++++++++++++++++++++++++++++

Once you are happy with a release file you can push it either
to another devpi-managed index or to an outside pypi index server.

Let's create another ``staging`` index::

    $ devpi index -c staging volatile=False
    http://localhost:3141/testuser/staging:
      type=stage
      bases=root/pypi
      volatile=False
      acl_upload=testuser
      pypi_whitelist=

We created a non-volatile index which means that one can not 
overwrite or delete release files. See :ref:`non_volatile_indexes` for more info
on this setting.

We can now push the ``example-1.0.tar.gz`` from above to
our ``staging`` index::

    $ devpi push example==1.0 testuser/staging
       200 register example 1.0 -> testuser/staging
       200 store_releasefile testuser/staging/+f/b5f/237f371f39108/example-1.0.tar.gz
       200 store_toxresult testuser/staging/+f/b5f/237f371f39108/example-1.0.tar.gz.toxresult0

This will determine all files on our ``testuser/dev`` index belonging to
the specified ``example==1.0`` release and copy them to the
``testuser/staging`` index. 

devpi push: releasing to an external index
++++++++++++++++++++++++++++++++++++++++++

Let's check again our current index::

    $ devpi use
    current devpi index: http://localhost:3141/testuser/dev (logged in as testuser)
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no

Let's now use our ``testuser/staging`` index::

    $ devpi use testuser/staging
    current devpi index: http://localhost:3141/testuser/staging (logged in as testuser)
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no

and check the test result status again::

    $ devpi list example
    http://localhost:3141/testuser/staging/+f/b5f/237f371f39108/example-1.0.tar.gz
    uwanda     linux2  python     2.7.6 tests failed

Good, the test result status is still available after the push
from the last step.

We may now decide to push this release to an external
pypi-style index which we have configured in the ``.pypirc`` file::

    $ devpi push example-1.0 pypi:testrun
    no pypirc file found at: /tmp/home/.pypirc

this will push all release files of the ``example-1.0`` release
to the external ``testrun`` index server, using credentials
and the URL found in the ``pypi`` section in your
``.pypirc``.

index inheritance re-configuration
++++++++++++++++++++++++++++++++++

At this point we have the ``example-1.0`` release and release file
on both the ``testuser/dev`` and ``testuser/staging`` indices.
If we rather want to always use staging packages in our development
index, we can reconfigure the inheritance 
``bases`` for ``testuser/dev``::

    $ devpi index testuser/dev bases=testuser/staging
    /testuser/dev changing bases: ['testuser/staging']
    http://localhost:3141/testuser/dev:
      type=stage
      bases=testuser/staging
      volatile=True
      acl_upload=testuser
      pypi_whitelist=

If we now switch back to using ``testuser/dev``::

    $ devpi use testuser/dev
    current devpi index: http://localhost:3141/testuser/dev (logged in as testuser)
    ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
    ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
    ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
    always-set-cfg: no

and look at our example release files::

    $ devpi list example
    http://localhost:3141/testuser/dev/+f/b5f/237f371f39108/example-1.0.tar.gz
    uwanda     linux2  python     2.7.6 tests failed
    http://localhost:3141/testuser/staging/+f/b5f/237f371f39108/example-1.0.tar.gz
    uwanda     linux2  python     2.7.6 tests failed

we'll see that ``example-1.0.tar.gz`` is contained in both
indices.  Let's remove the ``testuser/dev`` ``example`` release::

    $ devpi remove -y example
    About to remove the following releases and distributions
    version: 1.0
      - http://localhost:3141/testuser/dev/+f/b5f/237f371f39108/example-1.0.tar.gz
      - http://localhost:3141/testuser/dev/+f/b5f/237f371f39108/example-1.0.tar.gz.toxresult0
    Are you sure (yes/no)? yes (autoset from -y option)
    deleting release 1.0 of example

If you don't specify the ``-y`` option you will be asked to confirm
the delete operation interactively.

The ``example-1.0`` release remains accessible through ``testuser/dev``
because it inherits all releases from its ``testuser/staging`` base::

    $ devpi list example
    http://localhost:3141/testuser/staging/+f/b5f/237f371f39108/example-1.0.tar.gz
    uwanda     linux2  python     2.7.6 tests failed

::

    $ devpi-server --stop
    2015-11-11 14:43:25,877 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-11-11 14:43:25,877 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=12830

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to get some help.


