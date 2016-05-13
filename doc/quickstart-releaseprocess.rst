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

We need to perform a couple of steps to get an index
where we can upload and test packages:

- start a background devpi-server at ``http://localhost:3141``

- configure the client-side tool ``devpi`` to connect to the newly
  started server

- create and login a user, using as defaults your current login name 
  and an empty password.

- create an index and directly use it.

So let's first start a background server::

    $ devpi-server --start 
    2016-05-13 16:43:08,907 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 16:43:08,907 INFO  NOCTX generated uuid: ec7387e1df27416293a0d0e2f319bbdc
    2016-05-13 16:43:08,908 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 16:43:08,909 INFO  NOCTX DB: Creating schema
    2016-05-13 16:43:08,936 INFO  [Wtx-1] setting password for user u'root'
    2016-05-13 16:43:08,936 INFO  [Wtx-1] created user u'root' with email None
    2016-05-13 16:43:08,936 INFO  [Wtx-1] created root user
    2016-05-13 16:43:08,937 INFO  [Wtx-1] created root/pypi index
    2016-05-13 16:43:08,945 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=16719
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log

Then we point the devpi client to it::

    $ devpi use http://localhost:3141
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

Then we add our own "testuser"::

    $ devpi user -c testuser password=123
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

Then we login::

    $ devpi login testuser --password=123
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

And create a "dev" index, telling it to use the ``root/pypi`` cache as a base
so that all of pypi.python.org packages will appear on that index::

    $ devpi index -c dev bases=root/pypi
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

Finally we use the new index::

    $ devpi use testuser/dev
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

We are now ready to go for uploading and testing packages.

.. _`quickstart_release_steps`:

devpi install: installing a package
+++++++++++++++++++++++++++++++++++

We can now use the ``devpi`` command line client to trigger a ``pip
install`` of a pypi package using the index from our already running server::

    $ devpi install pytest
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

The ``devpi install`` command configured a pip call, using the
pypi-compatible ``+simple/`` page on our ``testuser/dev`` index for
finding and downloading packages.  The ``pip`` executable was searched
in the ``PATH`` and found in ``docenv/bin/pip``.

Let's check that ``pytest`` was installed correctly::

    $ py.test --version
    /bin/sh: 1: py.test: not found

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
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

Now go to the directory of a ``setup.py`` file of one of your projects  
(we assume it is named ``example``) to build and upload your package
to our ``testuser/dev`` index::

    example $ devpi upload
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

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
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

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
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

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
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

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
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

We created a non-volatile index which means that one can not 
overwrite or delete release files. See :ref:`non_volatile_indexes` for more info
on this setting.

We can now push the ``example-1.0.tar.gz`` from above to
our ``staging`` index::

    $ devpi push example==1.0 testuser/staging
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

This will determine all files on our ``testuser/dev`` index belonging to
the specified ``example==1.0`` release and copy them to the
``testuser/staging`` index. 

devpi push: releasing to an external index
++++++++++++++++++++++++++++++++++++++++++

Let's check again our current index::

    $ devpi use
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

Let's now use our ``testuser/staging`` index::

    $ devpi use testuser/staging
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

and check the test result status again::

    $ devpi list example
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

Good, the test result status is still available after the push
from the last step.

We may now decide to push this release to an external
pypi-style index which we have configured in the ``.pypirc`` file::

    $ devpi push example-1.0 pypi:testrun
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

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
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

If we now switch back to using ``testuser/dev``::

    $ devpi use testuser/dev
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

and look at our example release files::

    $ devpi list example
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

we'll see that ``example-1.0.tar.gz`` is contained in both
indices.  Let's remove the ``testuser/dev`` ``example`` release::

    $ devpi remove -y example
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

If you don't specify the ``-y`` option you will be asked to confirm
the delete operation interactively.

The ``example-1.0`` release remains accessible through ``testuser/dev``
because it inherits all releases from its ``testuser/staging`` base::

    $ devpi list example
    Traceback (most recent call last):
      File "/home/hpk/venv/0/bin/devpi", line 5, in <module>
        from pkg_resources import load_entry_point
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2927, in <module>
        @_call_aside
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2913, in _call_aside
        f(*args, **kwargs)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 2940, in _initialize_master_working_set
        working_set = WorkingSet._build_master()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 637, in _build_master
        return cls._build_from_requirements(__requires__)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 650, in _build_from_requirements
        dists = ws.resolve(reqs, Environment())
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/pkg_resources/__init__.py", line 829, in resolve
        raise DistributionNotFound(req, requirers)
    pkg_resources.DistributionNotFound: The 'devpi_common<3.0,>2.0.2' distribution was not found and is required by devpi-client

::

    $ devpi-server --stop
    2016-05-13 16:43:14,319 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2016-05-13 16:43:14,321 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    killed server pid=16719

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to get some help.


