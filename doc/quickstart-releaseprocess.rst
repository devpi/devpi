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

initializing a basic server and index
+++++++++++++++++++++++++++++++++++++

..
    $ rm -rf ~/.devpi/server

We need to perform a couple of steps to get an index
where we can upload and test packages:

- start a background devpi-server at ``http://localhost:3141``

- configure the client-side tool ``devpi`` to connect to the newly
  started server

- create and login a user, using as defaults your current login name 
  and an empty password.

- create an index and directly use it.

So let's first initialize devpi-server::

    $ devpi-init
    INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    INFO  NOCTX generated uuid: 04b0641862e241adbfd03deca26ac4ef
    INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    INFO  NOCTX DB: Creating schema
    INFO  [Wtx-1] setting password for user 'root'
    INFO  [Wtx-1] created user 'root' with email None
    INFO  [Wtx-1] created root user
    INFO  [Wtx-1] created root/pypi index
    INFO  [Wtx-1] fswriter0: committed: keys: '.config','root/.config'

To start ``devpi-server`` in the background we use supervisor as an example.
First we create the config file for it::

    $ devpi-gen-config
    It is highly recommended to use a configuration file for devpi-server, see --configfile option.
    wrote gen-config/crontab
    wrote gen-config/net.devpi.plist
    wrote gen-config/launchd-macos.txt
    wrote gen-config/nginx-devpi.conf
    wrote gen-config/supervisor-devpi.conf
    wrote gen-config/supervisord.conf
    wrote gen-config/devpi.service
    wrote gen-config/windows-service.txt

Then we start supervisord using a config which includes the generated file,
see :ref:`quickstart-server` for more details::

    $ supervisord -c gen-config/supervisord.conf

..
    $ sleep 6

Then we point the devpi client to it::

    $ devpi use http://localhost:3141
    using server: http://localhost:3141/ (not logged in)
    no current index: type 'devpi use -l' to discover indices
    venv for install/set commands: /tmp/docenv
    only setting venv pip cfg, no global configuration changed
    /tmp/docenv/pip.conf   : no config file exists
    always-set-cfg: no

Then we add our own "testuser"::

    $ devpi user -c testuser password=123
    user created: testuser

Then we login::

    $ devpi login testuser --password=123
    logged in 'testuser', credentials valid for 10.00 hours

And create a "dev" index, telling it to use the ``root/pypi`` cache as a base
so that all of pypi.org packages will appear on that index::

    $ devpi index -c dev bases=root/pypi
    http://localhost:3141/testuser/dev?no_projects=:
      type=stage
      bases=root/pypi
      volatile=True
      acl_upload=testuser
      acl_toxresult_upload=:ANONYMOUS:
      mirror_whitelist=

Finally we use the new index::

    $ devpi use testuser/dev
    current devpi index: http://localhost:3141/testuser/dev (logged in as testuser)
    supported features: server-keyvalue-parsing
    venv for install/set commands: /tmp/docenv
    only setting venv pip cfg, no global configuration changed
    /tmp/docenv/pip.conf   : no config file exists
    always-set-cfg: no

We are now ready to go for uploading and testing packages.

.. _`quickstart_release_steps`:

devpi install: installing a package
+++++++++++++++++++++++++++++++++++

We can now use the ``devpi`` command line client to trigger a ``pip
install`` of a pypi package using the index from our already running server::

    $ devpi install pytest
    -->  /home/devpi/devpi/doc$ /tmp/docenv/bin/pip install -U -i http://localhost:3141/testuser/dev/+simple/ pytest  [PIP_PRE=1,PIP_USE_WHEEL=1]
    Looking in indexes: http://localhost:3141/testuser/dev/+simple/
    Collecting pytest
      Downloading http://localhost:3141/root/pypi/%2Bf/f6a/567e20c04259d/pytest-5.3.0-py3-none-any.whl (233kB)
    Collecting packaging
      Downloading http://localhost:3141/root/pypi/%2Bf/d95/51545c6d761f3/packaging-19.2-py2.py3-none-any.whl
    Collecting attrs>=17.4.0
      Downloading http://localhost:3141/root/pypi/%2Bf/08a/96c641c3a74e4/attrs-19.3.0-py2.py3-none-any.whl
    Collecting importlib-metadata>=0.12; python_version < "3.8"
      Downloading http://localhost:3141/root/pypi/%2Bf/d5f/18a79777f3aa1/importlib_metadata-0.23-py2.py3-none-any.whl
    Collecting pluggy<1.0,>=0.12
      Downloading http://localhost:3141/root/pypi/%2Bf/0db/4b7601aae1d35/pluggy-0.13.0-py2.py3-none-any.whl
    Collecting wcwidth
      Downloading http://localhost:3141/root/pypi/%2Bf/f4e/be71925af7b40/wcwidth-0.1.7-py2.py3-none-any.whl
    Collecting more-itertools>=4.0.0
      Downloading http://localhost:3141/root/pypi/%2Bf/92b/8c4b06dac4f06/more_itertools-7.2.0-py3-none-any.whl (57kB)
    Requirement already satisfied, skipping upgrade: py>=1.5.0 in /private/tmp/docenv/lib/python3.6/site-packages (from pytest) (1.8.0)
    Collecting six
      Downloading http://localhost:3141/root/pypi/%2Bf/1f1/b7d42e254082a/six-1.13.0-py2.py3-none-any.whl
    Collecting pyparsing>=2.0.2
      Downloading http://localhost:3141/root/pypi/%2Bf/20f/995ecd72f2a1f/pyparsing-2.4.5-py2.py3-none-any.whl (67kB)
    Collecting zipp>=0.5
      Downloading http://localhost:3141/root/pypi/%2Bf/f06/903e9f1f43b12/zipp-0.6.0-py2.py3-none-any.whl
    Installing collected packages: six, pyparsing, packaging, attrs, more-itertools, zipp, importlib-metadata, pluggy, wcwidth, pytest
    Successfully installed attrs-19.3.0 importlib-metadata-0.23 more-itertools-7.2.0 packaging-19.2 pluggy-0.13.0 pyparsing-2.4.5 pytest-5.3.0 six-1.13.0 wcwidth-0.1.7 zipp-0.6.0

The ``devpi install`` command configured a pip call, using the
pypi-compatible ``+simple/`` page on our ``testuser/dev`` index for
finding and downloading packages.  The ``pip`` executable was searched
in the ``PATH`` and found in ``docenv/bin/pip``.

Let's check that ``pytest`` was installed correctly::

    $ py.test --version
    This is pytest version 5.3.0, imported from /tmp/docenv/lib/python3.6/site-packages/pytest.py

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
    supported features: server-keyvalue-parsing
    venv for install/set commands: /tmp/docenv
    only setting venv pip cfg, no global configuration changed
    /tmp/docenv/pip.conf   : no config file exists
    always-set-cfg: no

Now go to the directory of a ``setup.py`` file of one of your projects  
(we assume it is named ``example``) to build and upload your package
to our ``testuser/dev`` index::

    example $ devpi upload
    using workdir /tmp/devpi0
    pre-build: cleaning /home/devpi/devpi/doc/example/dist
    -->  /home/devpi/devpi/doc/example$ /tmp/docenv/bin/python setup.py sdist --formats gztar
    built: /home/devpi/devpi/doc/example/dist/example-1.0.tar.gz [SDIST.TGZ] 0.732kb
    register example-1.0 to http://localhost:3141/testuser/dev/
    file_upload of example-1.0.tar.gz to http://localhost:3141/testuser/dev/

There are three triggered actions:

- detection of a VCS (git/hg/svn/bazaar) repository, leading to copying all versioned
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
    -->  /home/devpi/devpi/doc$ /tmp/docenv/bin/pip install -U -i http://localhost:3141/testuser/dev/+simple/ example  [PIP_PRE=1,PIP_USE_WHEEL=1]
    Looking in indexes: http://localhost:3141/testuser/dev/+simple/
    Collecting example
      Downloading http://localhost:3141/testuser/dev/%2Bf/57d/278dbb43406c1/example-1.0.tar.gz
    Building wheels for collected packages: example
      Building wheel for example (setup.py): started
      Building wheel for example (setup.py): finished with status 'done'
      Created wheel for example: filename=example-1.0-cp36-none-any.whl size=1419 sha256=69c0a0b258d0932315487afe6c4748cdb141a135d668f3ebde10cfed6782b159
      Stored in directory: /tmp/home/Library/Caches/pip/wheels/03/77/9a/2fb26b2454d41596f48ebc3a024df179716e560bca3362e306
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
    received http://localhost:3141/testuser/dev/+f/57d/278dbb43406c1/example-1.0.tar.gz
    unpacking /tmp/devpi-test0/downloads/example-1.0.tar.gz to /tmp/devpi-test0/targz
    /private/tmp/devpi-test0/targz/example-1.0$ tox --installpkg /tmp/devpi-test0/downloads/example-1.0.tar.gz -i ALL=http://localhost:3141/testuser/dev/+simple/ --recreate --result-json /tmp/devpi-test0/targz/toxreport.json -c /tmp/devpi-test0/targz/example-1.0/tox.ini
    python create: /tmp/devpi-test0/targz/example-1.0/.tox/python
    python installdeps: pytest
    python inst: /tmp/devpi-test0/targz/example-1.0/.tox/.tmp/package/1/example-1.0.tar.gz
    python installed: attrs==19.3.0,example==1.0,importlib-metadata==0.23,more-itertools==7.2.0,packaging==19.2,pluggy==0.13.0,py==1.8.0,pyparsing==2.4.5,pytest==5.3.0,six==1.13.0,wcwidth==0.1.7,zipp==0.6.0
    python run-test-pre: PYTHONHASHSEED='3000998858'
    python run-test: commands[0] | py.test
    ============================= test session starts ==============================
    platform darwin -- Python 3.6.8, pytest-5.3.0, py-1.8.0, pluggy-0.13.0
    cachedir: /tmp/devpi-test0/targz/example-1.0/.tox/python/.pytest_cache
    rootdir: /private/tmp/devpi-test0/targz/example-1.0
    collected 1 item
    
    test_example.py .                                                        [100%]
    
    ============================== 1 passed in 0.01s ===============================
    ___________________________________ summary ____________________________________
      python: commands succeeded
      congratulations :)
    write json report at: /tmp/devpi-test0/targz/toxreport.json
    posting tox result data to http://localhost:3141/testuser/dev/+f/57d/278dbb43406c1/example-1.0.tar.gz
    successfully posted tox result data

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
    http://localhost:3141/testuser/dev/+f/57d/278dbb43406c1/example-1.0.tar.gz

.. versionadded:: 2.6

With ``--index`` you can get the release from another index. Full URLs to
another devpi-server are also supported.

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
    http://localhost:3141/testuser/staging?no_projects=:
      type=stage
      bases=
      volatile=False
      acl_upload=testuser
      acl_toxresult_upload=:ANONYMOUS:
      mirror_whitelist=

We created a non-volatile index which means that one can not 
overwrite or delete release files. See :ref:`non_volatile_indexes` for more info
on this setting.

We can now push the ``example-1.0.tar.gz`` from above to
our ``staging`` index::

    $ devpi push example==1.0 testuser/staging
       200 register example 1.0 -> testuser/staging
       200 store_releasefile testuser/staging/+f/57d/278dbb43406c1/example-1.0.tar.gz
       200 store_toxresult testuser/staging/+f/57d/278dbb43406c1/example-1.0.tar.gz.toxresult-20191121095811-0

This will determine all files on our ``testuser/dev`` index belonging to
the specified ``example==1.0`` release and copy them to the
``testuser/staging`` index. 

devpi push: releasing to an external index
++++++++++++++++++++++++++++++++++++++++++

Let's check again our current index::

    $ devpi use
    current devpi index: http://localhost:3141/testuser/dev (logged in as testuser)
    supported features: server-keyvalue-parsing
    venv for install/set commands: /tmp/docenv
    only setting venv pip cfg, no global configuration changed
    /tmp/docenv/pip.conf   : no config file exists
    always-set-cfg: no

Let's now use our ``testuser/staging`` index::

    $ devpi use testuser/staging
    current devpi index: http://localhost:3141/testuser/staging (logged in as testuser)
    supported features: server-keyvalue-parsing
    venv for install/set commands: /tmp/docenv
    only setting venv pip cfg, no global configuration changed
    /tmp/docenv/pip.conf   : no config file exists
    always-set-cfg: no

and check the test result status again::

    $ devpi list example
    http://localhost:3141/testuser/staging/+f/57d/278dbb43406c1/example-1.0.tar.gz

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
    /testuser/dev bases=testuser/staging
    http://localhost:3141/testuser/dev?no_projects=:
      type=stage
      bases=testuser/staging
      volatile=True
      acl_upload=testuser
      acl_toxresult_upload=:ANONYMOUS:
      mirror_whitelist=

If we now switch back to using ``testuser/dev``::

    $ devpi use testuser/dev
    current devpi index: http://localhost:3141/testuser/dev (logged in as testuser)
    supported features: server-keyvalue-parsing
    venv for install/set commands: /tmp/docenv
    only setting venv pip cfg, no global configuration changed
    /tmp/docenv/pip.conf   : no config file exists
    always-set-cfg: no

and look at our example release files::

    $ devpi list example
    http://localhost:3141/testuser/dev/+f/57d/278dbb43406c1/example-1.0.tar.gz
    http://localhost:3141/testuser/staging/+f/57d/278dbb43406c1/example-1.0.tar.gz

we'll see that ``example-1.0.tar.gz`` is contained in both
indices.  Let's remove the ``testuser/dev`` ``example`` release::

    $ devpi remove -y example
    About to remove the following releases and distributions
    version: 1.0
      - http://localhost:3141/testuser/dev/+f/57d/278dbb43406c1/example-1.0.tar.gz
      - http://localhost:3141/testuser/dev/+f/57d/278dbb43406c1/example-1.0.tar.gz.toxresult-20191121095809-0
    Are you sure (yes/no)? yes (autoset from -y option)

If you don't specify the ``-y`` option you will be asked to confirm
the delete operation interactively.

The ``example-1.0`` release remains accessible through ``testuser/dev``
because it inherits all releases from its ``testuser/staging`` base::

    $ devpi list example
    http://localhost:3141/testuser/staging/+f/57d/278dbb43406c1/example-1.0.tar.gz

Now shutdown supervisord which was started at the beginning of this tutorial::

    $ supervisorctl -c gen-config/supervisord.conf shutdown
    Shut down

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to get some help.


