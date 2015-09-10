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
    2015-09-10 11:05:56,221 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:56,222 INFO  NOCTX generated uuid: 4a61e5f1b7b64ee6bdfd38edc4b08b83
    2015-09-10 11:05:56,222 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:05:56,222 INFO  NOCTX DB: Creating schema
    2015-09-10 11:05:56,268 INFO  [Wtx-1] opening sql
    2015-09-10 11:05:56,269 INFO  [Wtx-1] setting password for user u'root'
    2015-09-10 11:05:56,270 INFO  [Wtx-1] created user u'root' with email None
    2015-09-10 11:05:56,270 INFO  [Wtx-1] created root user
    2015-09-10 11:05:56,271 INFO  [Wtx-1] created root/pypi index
    2015-09-10 11:05:56,291 INFO  [Wtx-1] fswriter0: committed: keys: u'.config',u'root/.config'
    starting background devpi-server at http://localhost:3141
    /tmp/home/.devpi/server/.xproc/devpi-server$ /home/hpk/venv/0/bin/devpi-server
    process u'devpi-server' started pid=21862
    devpi-server process startup detected
    logfile is at /tmp/home/.devpi/server/.xproc/devpi-server/xprocess.log
    -->  /home/hpk/p/devpi/doc$ devpi use http://localhost:3141 
    using server: http://localhost:3141/ (not logged in)
    no current index: type 'devpi use -l' to discover indices
    ~/.pydistutils.cfg     : no config file exists
    ~/.pip/pip.conf        : no config file exists
    ~/.buildout/default.cfg: no config file exists
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
    ~/.pydistutils.cfg     : no config file exists
    ~/.pip/pip.conf        : no config file exists
    ~/.buildout/default.cfg: no config file exists
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
    2.3.1

.. _`quickstart_release_steps`:

devpi install: installing a package
+++++++++++++++++++++++++++++++++++

We can now use the ``devpi`` command line client to trigger a ``pip
install`` of a pypi package using the index from our already running server::

    $ devpi install pytest
    -->  /home/hpk/p/devpi/doc$ /tmp/docenv/bin/pip install -U -i http://localhost:3141/testuser/dev/+simple/ pytest  [PIP_USE_WHEEL=1,PIP_PRE=1]
    Collecting pytest
      Could not find a version that satisfies the requirement pytest (from versions: )
    No matching distribution found for pytest
    command failed

The ``devpi install`` command configured a pip call, using the
pypi-compatible ``+simple/`` page on our ``testuser/dev`` index for
finding and downloading packages.  The ``pip`` executable was searched
in the ``PATH`` and found in ``docenv/bin/pip``.

Let's check that ``pytest`` was installed correctly::

    $ py.test --version
    This is pytest version 2.8.0.dev4, imported from /home/hpk/p/pytest-hpk/pytest.pyc
    setuptools registered plugins:
      pytest-cache-1.1.dev1 at /home/hpk/p/pytest-cache/pytest_cache.pyc
      pytest-xdist-1.12 at /home/hpk/p/pytest-xdist/xdist/plugin.pyc
      pytest-pep8-1.0.6 at /home/hpk/p/pytest-pep8/pytest_pep8.pyc
      pytest-xprocess-0.9 at /home/hpk/p/pytest-xprocess/pytest_xprocess.pyc
      pytest-capturelog-0.7 at /home/hpk/venv/0/local/lib/python2.7/site-packages/pytest_capturelog.pyc
      pytest-flakes-1.0.0 at /home/hpk/venv/0/local/lib/python2.7/site-packages/pytest_flakes.pyc
      pytest-cov-1.8.1 at /home/hpk/venv/0/local/lib/python2.7/site-packages/pytest_cov/__init__.pyc
      pytest-timeout-0.5 at /home/hpk/venv/0/local/lib/python2.7/site-packages/pytest_timeout.pyc

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
    ~/.pydistutils.cfg     : no config file exists
    ~/.pip/pip.conf        : no config file exists
    ~/.buildout/default.cfg: no config file exists
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
      Downloading http://localhost:3141/testuser/dev/+f/889/12b7eb53ffd81/example-1.0.tar.gz
    Building wheels for collected packages: example
      Running setup.py bdist_wheel for example
      Stored in directory: /tmp/home/.cache/pip/wheels/78/f9/d3/3078966652d8bdf1f79e5bf7400504b304d30e476446adab83
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
    received http://localhost:3141/testuser/dev/+f/889/12b7eb53ffd81/example-1.0.tar.gz
    unpacking /tmp/devpi-test0/downloads/example-1.0.tar.gz to /tmp/devpi-test0/targz
    /tmp/devpi-test0/targz/example-1.0$ tox --installpkg /tmp/devpi-test0/downloads/example-1.0.tar.gz -i ALL=http://localhost:3141/testuser/dev/+simple/ --recreate --result-json /tmp/devpi-test0/targz/toxreport.json -c /tmp/devpi-test0/targz/example-1.0/tox.ini
    python create: /tmp/devpi-test0/targz/example-1.0/.tox/python
    python installdeps: pytest
    ERROR: invocation failed (exit code 1), logfile: /tmp/devpi-test0/targz/example-1.0/.tox/python/log/python-1.log
    ERROR: actionid: python
    msg: getenv
    cmdargs: [local('/tmp/devpi-test0/targz/example-1.0/.tox/python/bin/pip'), 'install', '-i', 'http://localhost:3141/testuser/dev/+simple/', 'pytest']
    env: {'LC_PAPER': 'de_DE.UTF-8', 'VIRTUALENVWRAPPER_SCRIPT': '/home/hpk/venv/0/bin/virtualenvwrapper.sh', 'VIRTUAL_ENV': '/tmp/devpi-test0/targz/example-1.0/.tox/python', 'SHELL': '/bin/bash', 'XDG_DATA_DIRS': '/usr/share/ubuntu:/usr/share/gnome:/usr/local/share/:/usr/share/', 'MANDATORY_PATH': '/usr/share/gconf/ubuntu.mandatory.path', 'COMPIZ_CONFIG_PROFILE': 'ubuntu', 'JOB': 'dbus', 'SESSION': 'ubuntu', 'XMODIFIERS': '@im=ibus', 'JAVA_HOME': '/usr/lib/jvm/java-7-oracle', 'MFLAGS': '', 'SELINUX_INIT': 'YES', 'PIP_INDEX_URL': 'https://devpi.net/hpk/dev/', 'XDG_RUNTIME_DIR': '/run/user/1000', 'LC_ADDRESS': 'de_DE.UTF-8', 'COMPIZ_BIN_PATH': '/usr/bin/', 'J2SDKDIR': '/usr/lib/jvm/java-7-oracle', 'XDG_SESSION_ID': 'c2', 'DBUS_SESSION_BUS_ADDRESS': 'unix:abstract=/tmp/dbus-PDc07zA6o1', 'GNOME_KEYRING_PID': '2254', 'DESKTOP_SESSION': 'ubuntu', 'GTK_MODULES': 'overlay-scrollbar:unity-gtk-module', 'INSTANCE': '', 'LC_NAME': 'de_DE.UTF-8', 'XDG_MENU_PREFIX': 'gnome-', 'LS_COLORS': 'rs=0:di=01;34:ln=01;36:mh=00:pi=40;33:so=01;35:do=01;35:bd=40;33;01:cd=40;33;01:or=40;31;01:su=37;41:sg=30;43:ca=30;41:tw=30;42:ow=34;42:st=37;44:ex=01;32:*.tar=01;31:*.tgz=01;31:*.arj=01;31:*.taz=01;31:*.lzh=01;31:*.lzma=01;31:*.tlz=01;31:*.txz=01;31:*.zip=01;31:*.z=01;31:*.Z=01;31:*.dz=01;31:*.gz=01;31:*.lz=01;31:*.xz=01;31:*.bz2=01;31:*.bz=01;31:*.tbz=01;31:*.tbz2=01;31:*.tz=01;31:*.deb=01;31:*.rpm=01;31:*.jar=01;31:*.war=01;31:*.ear=01;31:*.sar=01;31:*.rar=01;31:*.ace=01;31:*.zoo=01;31:*.cpio=01;31:*.7z=01;31:*.rz=01;31:*.jpg=01;35:*.jpeg=01;35:*.gif=01;35:*.bmp=01;35:*.pbm=01;35:*.pgm=01;35:*.ppm=01;35:*.tga=01;35:*.xbm=01;35:*.xpm=01;35:*.tif=01;35:*.tiff=01;35:*.png=01;35:*.svg=01;35:*.svgz=01;35:*.mng=01;35:*.pcx=01;35:*.mov=01;35:*.mpg=01;35:*.mpeg=01;35:*.m2v=01;35:*.mkv=01;35:*.webm=01;35:*.ogm=01;35:*.mp4=01;35:*.m4v=01;35:*.mp4v=01;35:*.vob=01;35:*.qt=01;35:*.nuv=01;35:*.wmv=01;35:*.asf=01;35:*.rm=01;35:*.rmvb=01;35:*.flc=01;35:*.avi=01;35:*.fli=01;35:*.flv=01;35:*.gl=01;35:*.dl=01;35:*.xcf=01;35:*.xwd=01;35:*.yuv=01;35:*.cgm=01;35:*.emf=01;35:*.axv=01;35:*.anx=01;35:*.ogv=01;35:*.ogx=01;35:*.aac=00;36:*.au=00;36:*.flac=00;36:*.mid=00;36:*.midi=00;36:*.mka=00;36:*.mp3=00;36:*.mpc=00;36:*.ogg=00;36:*.ra=00;36:*.wav=00;36:*.axa=00;36:*.oga=00;36:*.spx=00;36:*.xspf=00;36:', 'LC_NUMERIC': 'de_DE.UTF-8', 'GNOME_DESKTOP_SESSION_ID': 'this-is-deprecated', 'LESSOPEN': '| /usr/bin/lesspipe %s', 'USER': 'testuser', 'XDG_VTNR': '7', 'PS1': '(docenv)(0)\\[\\e]0;\\u@\\h: \\w\\a\\]${debian_chroot:+($debian_chroot)}\\[\\033[01;32m\\]\\u@\\h\\[\\033[00m\\]:\\[\\033[01;34m\\]\\w\\[\\033[00m\\]$(__git_ps1)\\$ ', 'XAUTHORITY': '/home/hpk/.Xauthority', 'LANGUAGE': 'en_US', 'SESSION_MANAGER': 'local/cobra:@/tmp/.ICE-unix/2465,unix/cobra:/tmp/.ICE-unix/2465', 'SHLVL': '1', 'QT_QPA_PLATFORMTHEME': 'appmenu-qt5', 'CLUTTER_IM_MODULE': 'xim', 'WINDOWID': '29360139', 'EDITOR': 'vim', 'GPG_AGENT_INFO': '/run/user/1000/keyring-2akVyb/gpg:0:1', 'VENV_DIR': '/tmp/docenv', 'GDMSESSION': 'ubuntu', 'XDG_SEAT_PATH': '/org/freedesktop/DisplayManager/Seat0', 'TMPDIR': '/tmp', 'GTK_IM_MODULE': 'ibus', 'XDG_CONFIG_DIRS': '/etc/xdg/xdg-ubuntu:/usr/share/upstart/xdg:/etc/xdg', 'COLORTERM': 'gnome-terminal', 'LC_TIME': 'de_DE.UTF-8', 'XDG_GREETER_DATA_DIR': '/var/lib/lightdm-data/hpk', 'QT4_IM_MODULE': 'xim', 'HOME': '/tmp/home', 'DISPLAY': ':0', 'LANG': 'en_US.UTF-8', 'MAILDIR': '/home/hpk/Maildir', 'LC_MONETARY': 'de_DE.UTF-8', 'TEXTDOMAIN': 'im-config', '_': '/usr/bin/make', 'TESTHOME': '/tmp/home', 'GTIMELOG_HOME': '/home/hpk/hpk42/timetrack', 'LC_IDENTIFICATION': 'de_DE.UTF-8', 'VTE_VERSION': '3409', 'PIP_VIRTUALENV_BASE': '/home/hpk/venv', 'XDG_CURRENT_DESKTOP': 'Unity', 'LESSCLOSE': '/usr/bin/lesspipe %s %s', 'VIRTUALENVWRAPPER_HOOK_DIR': '/home/hpk/venv', 'MAKELEVEL': '1', 'LOGNAME': 'hpk', 'J2REDIR': '/usr/lib/jvm/java-7-oracle/jre', 'WORKON_HOME': '/home/hpk/venv', 'QT_IM_MODULE': 'ibus', 'DEVPI_CLIENTDIR': '/tmp/home/.devpi/client', 'XDG_SEAT': 'seat0', 'GNOME_KEYRING_CONTROL': '/run/user/1000/keyring-2akVyb', 'PATH': '/tmp/devpi-test0/targz/example-1.0/.tox/python/bin:/tmp/docenv/bin:/home/hpk/bin:/home/hpk/venv/0/bin:/usr/local/bin:/home/hpk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/usr/lib/jvm/java-7-oracle/bin:/usr/lib/jvm/java-7-oracle/db/bin:/usr/lib/jvm/java-7-oracle/jre/bin', 'MAKEFLAGS': '', 'TERM': 'xterm', 'XDG_SESSION_PATH': '/org/freedesktop/DisplayManager/Session0', 'DEFAULTS_PATH': '/usr/share/gconf/ubuntu.default.path', 'SESSIONTYPE': 'gnome-session', 'IM_CONFIG_PHASE': '1', 'PYTHONHASHSEED': '1905301645', 'SSH_AUTH_SOCK': '/run/user/1000/keyring-2akVyb/ssh', 'DEVPI_SERVERDIR': '/tmp/home/.devpi/server', 'TEXTDOMAINDIR': '/usr/share/locale/', 'VIRTUALENVWRAPPER_PROJECT_FILENAME': '.project', 'DERBY_HOME': '/usr/lib/jvm/java-7-oracle/db', 'UPSTART_SESSION': 'unix:abstract=/com/ubuntu/upstart-session/1000/2269', 'PYTHONSTARTUP': '/home/hpk/python/start.py', 'OLDPWD': '/home/hpk/p/devpi', 'GPGKEY': '79B772D6', 'GDM_LANG': 'en_US', 'LC_TELEPHONE': 'de_DE.UTF-8', 'LC_MEASUREMENT': 'de_DE.UTF-8', 'PWD': '/home/hpk/p/devpi/doc'}
    
    Collecting pytest
      Could not find a version that satisfies the requirement pytest (from versions: )
    No matching distribution found for pytest
    
    ERROR: could not install deps [pytest]; v = InvocationError('/tmp/devpi-test0/targz/example-1.0/.tox/python/bin/pip install -i http://localhost:3141/testuser/dev/+simple/ pytest (see /tmp/devpi-test0/targz/example-1.0/.tox/python/log/python-1.log)', 1)
    ___________________________________ summary ____________________________________
    ERROR:   python: could not install deps [pytest]; v = InvocationError('/tmp/devpi-test0/targz/example-1.0/.tox/python/bin/pip install -i http://localhost:3141/testuser/dev/+simple/ pytest (see /tmp/devpi-test0/targz/example-1.0/.tox/python/log/python-1.log)', 1)
    wrote json report at: /tmp/devpi-test0/targz/toxreport.json
    posting tox result data to http://localhost:3141/testuser/dev/+f/889/12b7eb53ffd81/example-1.0.tar.gz
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
    http://localhost:3141/testuser/dev/+f/889/12b7eb53ffd81/example-1.0.tar.gz
    cobra      linux2  python     setup failed
    cobra      linux2  python     no tests were run

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
       200 store_releasefile testuser/staging/+f/889/12b7eb53ffd81/example-1.0.tar.gz
       200 store_toxresult testuser/staging/+f/889/12b7eb53ffd81/example-1.0.tar.gz.toxresult0

This will determine all files on our ``testuser/dev`` index belonging to
the specified ``example==1.0`` release and copy them to the
``testuser/staging`` index. 

devpi push: releasing to an external index
++++++++++++++++++++++++++++++++++++++++++

Let's check again our current index::

    $ devpi use
    current devpi index: http://localhost:3141/testuser/dev (logged in as testuser)
    ~/.pydistutils.cfg     : no config file exists
    ~/.pip/pip.conf        : no config file exists
    ~/.buildout/default.cfg: no config file exists
    always-set-cfg: no

Let's now use our ``testuser/staging`` index::

    $ devpi use testuser/staging
    current devpi index: http://localhost:3141/testuser/staging (logged in as testuser)
    ~/.pydistutils.cfg     : no config file exists
    ~/.pip/pip.conf        : no config file exists
    ~/.buildout/default.cfg: no config file exists
    always-set-cfg: no

and check the test result status again::

    $ devpi list example
    http://localhost:3141/testuser/staging/+f/889/12b7eb53ffd81/example-1.0.tar.gz
    cobra      linux2  python     setup failed
    cobra      linux2  python     no tests were run

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
    ~/.pydistutils.cfg     : no config file exists
    ~/.pip/pip.conf        : no config file exists
    ~/.buildout/default.cfg: no config file exists
    always-set-cfg: no

and look at our example release files::

    $ devpi list example
    http://localhost:3141/testuser/dev/+f/889/12b7eb53ffd81/example-1.0.tar.gz
    cobra      linux2  python     setup failed
    cobra      linux2  python     no tests were run
    http://localhost:3141/testuser/staging/+f/889/12b7eb53ffd81/example-1.0.tar.gz
    cobra      linux2  python     setup failed
    cobra      linux2  python     no tests were run

we'll see that ``example-1.0.tar.gz`` is contained in both
indices.  Let's remove the ``testuser/dev`` ``example`` release::

    $ devpi remove -y example
    About to remove the following releases and distributions
    version: 1.0
      - http://localhost:3141/testuser/dev/+f/889/12b7eb53ffd81/example-1.0.tar.gz
      - http://localhost:3141/testuser/dev/+f/889/12b7eb53ffd81/example-1.0.tar.gz.toxresult0
    Are you sure (yes/no)? yes (autoset from -y option)
    deleting release 1.0 of example

If you don't specify the ``-y`` option you will be asked to confirm
the delete operation interactively.

The ``example-1.0`` release remains accessible through ``testuser/dev``
because it inherits all releases from its ``testuser/staging`` base::

    $ devpi list example
    http://localhost:3141/testuser/staging/+f/889/12b7eb53ffd81/example-1.0.tar.gz
    cobra      linux2  python     setup failed
    cobra      linux2  python     no tests were run

::

    $ devpi-server --stop
    2015-09-10 11:06:12,620 INFO  NOCTX Loading node info from /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:06:12,621 INFO  NOCTX wrote nodeinfo to: /tmp/home/.devpi/server/.nodeinfo
    2015-09-10 11:06:12,624 INFO  [Wtx10] opening sql
    killed server pid=21862

running devpi-server permanently
+++++++++++++++++++++++++++++++++

If you want to configure a permanent devpi-server install,
you can go to :ref:`quickstart-server` to get some help.


