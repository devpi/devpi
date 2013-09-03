.. _label_userman_commandref:

devpi command reference (client)
================================

.. include:: ../links.rst

.. sidebar:: Summary

      Complete devpi command reference.

.. _cmdref_getjson:

getjson
-------

::

    $ devpi getjson -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi getjson
           [-h] [--version] [--debug] [-y] [--clientdir DIR] path
    
    show remote server and index configuration. A low-level command to show json-
    formatted configuration data from remote resources. This will always query the
    remote server.
    
    positional arguments:
      path             path to a resource to show information on. examples: '/',
                       '/user', '/user/index'.
    
    optional arguments:
      -h, --help       show this help message and exit
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_index:

index
-----

::

    $ devpi index -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi index
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [-c | --delete | -l]
           [indexname] [keyvalues [keyvalues ...]]
    
    create, delete and manage indexes. This is the central command to create and
    manipulate indexes. The index is always created under the currently logged in
    user with a command like this: ``devpi index -c newindex``. You can also view
    the configuration of any index with ``devpi index USER/INDEX`` or list all
    indexes of the in-use index with ``devpi index -l``.
    
    positional arguments:
      indexname        index name, specified as NAME or USER/NAME. If no index is
                       specified use the current index
      keyvalues        key=value configuration item. Possible key=value are
                       bases=CSV, volatile=True|False, acl_upload=CSV)
    
    optional arguments:
      -h, --help       show this help message and exit
      -c, --create     create an index
      --delete         delete an index
      -l, --list       list indexes for the logged in user
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_install:

install
-------

::

    $ devpi install -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi install
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [-l] [-e ARG]
           [--venv DIR]
           [pkg [pkg ...]]
    
    install packages through current devpi index. This is convenience wrapper
    which configures and invokes ``pip install`` commands for you, using the
    current index.
    
    positional arguments:
      pkg              uri or package file for installation from current index.
    
    optional arguments:
      -h, --help       show this help message and exit
      -l               print list of currently installed packages.
      -e ARG           install a project in editable mode.
      --venv DIR       install into specified virtualenv (created on the fly if
                       none exists).
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_list:

list
----

::

    $ devpi list -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi list
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [-f] [spec]
    
    list project versions and files for the current index. Without a ``spec``
    argument this command will show the names of all projects that have been used.
    With a spec argument it will show all release files. RED files come from an an
    inherited version which is shadowed by an inheriting index.
    
    positional arguments:
      spec             show only info for a project/version/release file. Example
                       specs: 'pytest' or 'pytest-2.3.5' or 'pytest-2.3.5.tar.gz'
    
    optional arguments:
      -h, --help       show this help message and exit
      -f, --failures   show test setup/failure logs
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_login:

login
-----

::

    $ devpi login -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi login
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [--password PASSWORD]
           username
    
    login to devpi-server with the specified user. This command performs the login
    protocol with the remove server which typically results in a cached auth token
    which is valid for ten hours. You can check your login information with "devpi
    use".
    
    positional arguments:
      username             username to use for login
    
    optional arguments:
      -h, --help           show this help message and exit
      --password PASSWORD  password to use for login (prompt if not set)
    
    generic options:
      --version            show program's version number and exit
      --debug              show debug messages including more info on server
                           requests
      -y                   assume 'yes' on confirmation questions
      --clientdir DIR      directory for storing login and other state

.. _cmdref_logoff:

logoff
------

::

    $ devpi logoff -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi logoff
           [-h] [--version] [--debug] [-y] [--clientdir DIR]
    
    log out of the current devpi-server. This will erase the client-side login
    token (see "devpi login").
    
    optional arguments:
      -h, --help       show this help message and exit
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_push:

push
----

::

    $ devpi push -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi push
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [--pypirc path]
           NAME-VER TARGETSPEC
    
    push a release and releasefiles to an internal or external index. You can push
    a release with all its release files either to an external pypi server
    ("pypi:REPONAME") where REPONAME needs to be defined in your ``.pypirc`` file.
    Or you can push to another devpi index ("user/name").
    
    positional arguments:
      NAME-VER         release in format 'name-version'. of which the metadata and
                       all release files are to be uploaded to the specified
                       external pypi repo.
      TARGETSPEC       local or remote target index. local targets are of form
                       'USER/NAME', specifying an existing writeable local index.
                       remote targets are of form 'REPO:' where REPO must be an
                       existing entry in the pypirc file.
    
    optional arguments:
      -h, --help       show this help message and exit
      --pypirc path    path to pypirc
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_quickstart:

quickstart
----------

::

    $ devpi quickstart -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi quickstart
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [--user USER]
           [--password PASSWORD] [--index INDEX] [--dry-run]
    
    start a server, create a user and login, then create a USER/dev index and then
    connect to this index, so that subsequent devpi commands can work with it.
    
    optional arguments:
      -h, --help           show this help message and exit
      --user USER          set initial user name to create and login
      --password PASSWORD  initial password (default is empty)
      --index INDEX        initial index name for the user.
      --dry-run            don't perform any actions, just show them
    
    generic options:
      --version            show program's version number and exit
      --debug              show debug messages including more info on server
                           requests
      -y                   assume 'yes' on confirmation questions
      --clientdir DIR      directory for storing login and other state

.. _cmdref_remove:

remove
------

::

    $ devpi remove -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi remove
           [-h] [--version] [--debug] [-y] [--clientdir DIR] spec
    
    remove project info/files from current index. This command allows to remove
    projects or releases from your current index (see "devpi use"). It will ask
    interactively for confirmation before performing the actual removals.
    
    positional arguments:
      spec             remove info/files for a project/version/release file from
                       the current index. Example specs: 'pytest' or
                       'pytest-2.3.5' or 'pytest-2.3.5.tar.gz'
    
    optional arguments:
      -h, --help       show this help message and exit
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_test:

test
----

::

    $ devpi test -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi test
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [-e VENV] pkgspec
    
    download and test a package against tox environments. Download a package and
    run tests as configured by the tox.ini file (which must be contained in the
    package).
    
    positional arguments:
      pkgspec          package specification to download and test
    
    optional arguments:
      -h, --help       show this help message and exit
      -e VENV          virtual environment to run from the tox.ini
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_upload:

upload
------

::

    $ devpi upload -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi upload
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [--ver SETVERSION]
           [--formats FORMATS] [--from-dir FROMDIR] [--only-latest] [--dry-run]
           [--with-docs] [--only-docs]
    
    prepare and upload packages to the current index. This command wraps
    ``setup.py`` invocations to build and upload releases, release files and
    documentation to your in-use index (see "devpi use").
    
    optional arguments:
      -h, --help          show this help message and exit
      --ver SETVERSION    fill version string into setup.py, */__init__.py
                          */conf.py files
      --formats FORMATS   comma separated list of build formats (passed to
                          setup.py). Examples
                          sdist.zip,bdist_egg,bdist_wheel,bdist_dumb.
      --from-dir FROMDIR  upload all archive files from the specified directory
      --only-latest       upload only latest version if multiple archives for a
                          package are found (only effective with --from-dir)
      --dry-run           don't perform any server-modifying actions
      --with-docs         build sphinx docs and upload them to index. this
                          triggers 'setup.py build_sphinx ... upload_docs ...'
      --only-docs         as --with-docs but don't upload release files
    
    generic options:
      --version           show program's version number and exit
      --debug             show debug messages including more info on server
                          requests
      -y                  assume 'yes' on confirmation questions
      --clientdir DIR     directory for storing login and other state

.. _cmdref_use:

use
---

::

    $ devpi use -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi use
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [--venv VENV]
           [--urls] [-l] [--delete]
           [url]
    
    show/configure current index and target venv for install activities. This
    shows client-side state, relevant for server interactions, including login
    authentication information, the current remote index (and API endpoints if you
    specify --urls) and the target virtualenv for installation activities.
    
    positional arguments:
      url              set current API endpoints to the ones obtained from the
                       given url. If already connected to a server, you can
                       specify '/USER/INDEXNAME' which will use the same server
                       context. If you specify the root url you will not be
                       connected to a particular index.
    
    optional arguments:
      -h, --help       show this help message and exit
      --venv VENV      set virtual environment to use for install activities.
                       specify '-' to unset it.
      --urls           show remote endpoint urls
      -l               show all available indexes at the remote server
      --delete         delete current association with server
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _cmdref_user:

user
----

::

    $ devpi user -h
    usage: /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/devpi user
           [-h] [--version] [--debug] [-y] [--clientdir DIR] [-c] [--delete] [-m]
           [-l]
           [username] [keyvalues [keyvalues ...]]
    
    add, remove, modify, list user configuration. This is the central command for
    performing remote user configuration and manipulation. Each indexes (created
    in turn by "devpi index" command) is owned by a particular user. If you create
    a user you either need to pass a ``password=...`` setting or interactively
    type a password.
    
    positional arguments:
      username         user name
      keyvalues        key=value configuration item. Possible keys: email,
                       password.
    
    optional arguments:
      -h, --help       show this help message and exit
      -c, --create     create a user
      --delete         delete a user
      -m, --modify     modify user settings
      -l, --list       list user names
    
    generic options:
      --version        show program's version number and exit
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      --clientdir DIR  directory for storing login and other state

.. _`cmdref_devpi_server`:

devpi command reference (server)
================================

::

    $ devpi-server -h
    usage: devpi-server [-h] [--version] [--serverdir DIR] [--host HOST]
                        [--port PORT] [--outside-url URL] [--refresh SECS]
                        [--bypass-cdn] [--passwd USER] [--gendeploy DIR]
                        [--secretfile path] [--bottleserver TYPE] [--debug]
                        [--start] [--stop] [--status] [--log]
    
    Start an index server acting as a cache for pypi.python.org, suitable for
    pip/easy_install usage. The server automatically refreshes the cache of all
    indexes which have changed on the pypi.python.org side.
    
    optional arguments:
      -h, --help           show this help message and exit
    
    main options:
      --version            show devpi_version (1.0)
      --serverdir DIR      directory for server data. By default, $DEVPI_SERVERDIR
                           is used if it exists, otherwise the default is
                           '~/.devpi/server'
      --host HOST          domain/ip address to listen on [localhost]
      --port PORT          port to listen for http requests. When used with
                           --gendeploy, port+1 will be used to prevent accidental
                           clashes with ad-hoc runs. [3141]
      --outside-url URL    the outside URL where this server will be reachable.
                           Set this if you proxy devpi-server through a web server
                           and the web server does not set or you want to override
                           the custom X-outside-url header.
      --refresh SECS       interval for consulting changelog api of
                           pypi.python.org [60]
      --bypass-cdn         set this if you want to bypass pypi's CDN for access to
                           simple pages and packages, in order to rule out cache-
                           invalidation issues. This will only work if you are not
                           using a http proxy.
      --passwd USER        set password for user USER (interactive)
      --gendeploy DIR      (unix only) install and generate a pre-configured
                           virtualenv directory which puts devpi-server under
                           supervisor control and provides some example files for
                           nginx/crontab. If the specified DIR exists virtualenv
                           creation will be skipped and only the installation
                           steps will be performed.
      --secretfile path    file containing the server side secret used for user
                           validation. If it does not exist, a random secret is
                           generated on start up and used subsequently.
                           [{serverdir}/.secret]
      --bottleserver TYPE  bottle server class, tries 'eventlet', then 'wsgiref'
                           if set to 'auto' (default) [auto]
      --debug              run wsgi application with debug logging
    
    background server:
      --start              start the background devpi-server
      --stop               stop the background devpi-server
      --status             show status of background devpi-server
      --log                show logfile content of background server
