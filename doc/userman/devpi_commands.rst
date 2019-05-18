.. _label_userman_commandref:

devpi command reference (client)
================================

.. include:: ../links.rst

Summary
-------

Complete devpi command reference.

.. _cmdref_getjson:

getjson
-------

::

    $ devpi getjson -h
    usage: devpi getjson [-h] [--debug] [-y] [-v] [--clientdir DIR] path_or_url
    
    show remote server and index configuration. A low-level command to show json-
    formatted configuration data from remote resources. This will always query the
    remote server.
    
    positional arguments:
      path_or_url      path or url of a resource to show information on. examples:
                       '/', '/user', '/user/index'.
    
    optional arguments:
      -h, --help       show this help message and exit
    
    generic options:
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      -v, --verbose    increase verbosity
      --clientdir DIR  directory for storing login and other state

.. _cmdref_index:

index
-----

::

    $ devpi index -h
    usage: devpi index [-h] [--debug] [-y] [-v] [--clientdir DIR]
                       [-c | --delete | -l]
                       [indexname] [keyvalues [keyvalues ...]]
    
    create, delete and manage indexes. This is the central command to create and
    manipulate indexes. The index is always created under the currently logged in
    user with a command like this: ``devpi index -c newindex``. You can also view
    the configuration of any index with ``devpi index USER/INDEX`` or list all
    indexes of the in-use index with ``devpi index -l``. For the ``keyvalues``
    option CSV means "Comma Separated Value", in other words, a list of values
    separated by commas.
    
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
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      -v, --verbose    increase verbosity
      --clientdir DIR  directory for storing login and other state

.. _cmdref_install:

install
-------

::

    $ devpi install -h
    usage: devpi install [-h] [--debug] [-y] [-v] [--clientdir DIR]
                         [--index INDEX] [-l] [-e ARG] [--venv DIR] [-r]
                         [pkg [pkg ...]]
    
    install packages through current devpi index. This is convenience wrapper
    which configures and invokes ``pip install`` commands for you, using the
    current index.
    
    positional arguments:
      pkg                uri or package file for installation from current index.
    
    optional arguments:
      -h, --help         show this help message and exit
      --index INDEX      index to get package from (defaults to current index)
      -l                 print list of currently installed packages.
      -e ARG             install a project in editable mode.
      --venv DIR         install into specified virtualenv (created on the fly if
                         none exists).
      -r, --requirement  Install from the given requirements file.
    
    generic options:
      --debug            show debug messages including more info on server
                         requests
      -y                 assume 'yes' on confirmation questions
      -v, --verbose      increase verbosity
      --clientdir DIR    directory for storing login and other state

.. _cmdref_list:

list
----

::

    $ devpi list -h
    usage: devpi list [-h] [--debug] [-y] [-v] [--clientdir DIR] [-f] [--all] [-t]
                      [--index INDEX]
                      [spec]
    
    list project versions and files for the current index. Without a spec argument
    this command will show the names of all projects which have releases on the
    current index. You can use a pip/setuptools style spec argument to show files
    for particular versions of a project. RED files come from an an inherited
    version which is shadowed by an inheriting index.
    
    positional arguments:
      spec              show info for a project or a specific release. Example
                        specs: pytest or 'pytest>=2.3.5' (Quotes are needed to
                        prevent shell redirection)
    
    optional arguments:
      -h, --help        show this help message and exit
      -f, --failures    show test setup/failure logs (implies -t)
      --all             show all versions instead of just the newest
      -t, --toxresults  show toxresults for the releases
      --index INDEX     index to look at (defaults to current index)
    
    generic options:
      --debug           show debug messages including more info on server requests
      -y                assume 'yes' on confirmation questions
      -v, --verbose     increase verbosity
      --clientdir DIR   directory for storing login and other state

.. _cmdref_login:

login
-----

::

    $ devpi login -h
    usage: devpi login [-h] [--debug] [-y] [-v] [--clientdir DIR]
                       [--password PASSWORD]
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
      --debug              show debug messages including more info on server
                           requests
      -y                   assume 'yes' on confirmation questions
      -v, --verbose        increase verbosity
      --clientdir DIR      directory for storing login and other state

.. _cmdref_logoff:

logoff
------

::

    $ devpi logoff -h
    usage: devpi logoff [-h] [--debug] [-y] [-v] [--clientdir DIR]
    
    log out of the current devpi-server. This will erase the client-side login
    token (see "devpi login").
    
    optional arguments:
      -h, --help       show this help message and exit
    
    generic options:
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      -v, --verbose    increase verbosity
      --clientdir DIR  directory for storing login and other state

.. _cmdref_push:

push
----

::

    $ devpi push -h
    usage: devpi push [-h] [--debug] [-y] [-v] [--clientdir DIR] [--index INDEX]
                      [--pypirc path]
                      pkgspec TARGETSPEC
    
    push a release and releasefiles to an internal or external index. You can push
    a release with all its release files either to an external pypi server
    ("pypi:REPONAME") where REPONAME needs to be defined in your ``.pypirc`` file.
    Or you can push to another devpi index ("user/name").
    
    positional arguments:
      pkgspec          release in format 'name==version'. of which the metadata
                       and all release files are to be uploaded to the specified
                       external pypi repo.
      TARGETSPEC       local or remote target index. local targets are of form
                       'USER/NAME', specifying an existing writeable local index.
                       remote targets are of form 'REPO:' where REPO must be an
                       existing entry in the pypirc file.
    
    optional arguments:
      -h, --help       show this help message and exit
      --index INDEX    index to push from (defaults to current index)
      --pypirc path    path to pypirc
    
    generic options:
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      -v, --verbose    increase verbosity
      --clientdir DIR  directory for storing login and other state

.. _cmdref_remove:

remove
------

::

    $ devpi remove -h
    usage: devpi remove [-h] [--debug] [-y] [-v] [--clientdir DIR] [--index INDEX]
                        spec_or_url
    
    removes project info/files from current index.
    
    This command allows to remove projects or releases from your current index
    (see "devpi use").
    It will ask interactively for confirmation before performing the actual removals.
    
    positional arguments:
      spec_or_url      describes project/version/release file(s) to release from
                       the current index. If the spec starts with 'http://' or
                       'https://', it is considered as a request to delete a
                       single file.
    
    optional arguments:
      -h, --help       show this help message and exit
      --index INDEX    index to remove from (defaults to current index)
    
    generic options:
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      -v, --verbose    increase verbosity
      --clientdir DIR  directory for storing login and other state
    
    examples:
      devpi remove pytest
    
      devpi remove pytest>=2.3.5
    
      devpi remove https://mydevpi.org/dev/+f/1cf/3d6eaa6cbc5fa/pytest-1.0.zip

.. _cmdref_test:

test
----

::

    $ devpi test -h
    usage: devpi test [-h] [--debug] [-y] [-v] [--clientdir DIR] [-e ENVNAME]
                      [-c PATH] [--fallback-ini PATH] [--tox-args toxargs]
                      [--detox] [--no-upload] [--index INDEX] [--select SELECTOR]
                      [--list]
                      pkgspec [pkgspec ...]
    
    download and test a package against tox environments. Download a package and
    run tests as configured by the tox.ini file (which must be contained in the
    package).
    
    positional arguments:
      pkgspec               package specification in pip/setuptools requirement-
                            syntax, e.g. 'pytest' or 'pytest==2.4.2'
    
    optional arguments:
      -h, --help            show this help message and exit
      -e ENVNAME            tox test environment to run from the tox.ini
      -c PATH               tox configuration file to use with unpacked package
      --fallback-ini PATH   tox ini file to be used if the downloaded package has
                            none
      --tox-args toxargs    extra command line arguments for tox. e.g.
                            --toxargs="-c othertox.ini"
      --detox, -d           (experimental) run tests concurrently in multiple
                            processes using the detox tool (which must be
                            installed)
      --no-upload           Skip upload of tox results
      --index INDEX         index to get package from, defaults to current index.
                            Either just the NAME, using the current user,
                            USER/NAME using the current server or a full URL for
                            another server.
      --select SELECTOR, -s SELECTOR
                            Selector for release files. This is a regular
                            expression to select release files for which tests
                            will be run. With this option it's possible to select
                            wheels that aren't universal, or run tests only for
                            one specific release file.
      --list, -l            Just list the release files which would be tested.
    
    generic options:
      --debug               show debug messages including more info on server
                            requests
      -y                    assume 'yes' on confirmation questions
      -v, --verbose         increase verbosity
      --clientdir DIR       directory for storing login and other state

.. _cmdref_upload:

upload
------

::

    $ devpi upload -h
    usage: devpi upload [-h] [--debug] [-y] [-v] [--clientdir DIR] [-p PYTHON_EXE]
                        [--no-vcs] [--setupdir-only] [--formats FORMATS]
                        [--with-docs] [--only-docs] [--index INDEX] [--from-dir]
                        [--only-latest] [--dry-run]
                        [path [path ...]]
    
    (build and) upload packages to the current devpi-server index. You can
    directly upload existing release files by specifying their file system path as
    positional arguments. Such release files need to contain package metadata as
    created by setup.py or wheel invocations. Or, if you don't specify any path, a
    setup.py file must exist and will be used to perform build and upload
    commands. If you have a ``setup.cfg`` file you can have a "[devpi:upload]"
    section with ``formats``, ``no-vcs = 1``, and ``setupdir-only = 1`` settings
    providing defaults for the respective command line options.
    
    optional arguments:
      -h, --help            show this help message and exit
    
    generic options:
      --debug               show debug messages including more info on server
                            requests
      -y                    assume 'yes' on confirmation questions
      -v, --verbose         increase verbosity
      --clientdir DIR       directory for storing login and other state
    
    build options:
      -p PYTHON_EXE, --python PYTHON_EXE
                            Specify which Python interpreter to use.
      --no-vcs              don't VCS-export to a fresh dir, just execute setup.py
                            scripts directly using their dirname as current dir.
                            By default git/hg/svn/bazaar are auto-detected and
                            packaging is run from a fresh directory with all
                            versioned files exported.
      --setupdir-only       VCS-export only the directory containing setup.py
      --formats FORMATS     comma separated list of build formats (passed to
                            setup.py). Examples
                            sdist.zip,bdist_egg,bdist_wheel,bdist_dumb.
      --with-docs           build sphinx docs and upload them to index. this
                            triggers 'setup.py build_sphinx' for building
      --only-docs           as --with-docs but don't build or upload release files
    
    direct file upload options:
      --index INDEX         index to upload to (defaults to current index)
      --from-dir            recursively look for archive files in path if it is a
                            dir
      --only-latest         upload only latest version if multiple archives for a
                            package are found (only effective with --from-dir)
      --dry-run             don't perform any server-modifying actions
      path                  path to archive file to be inspected and uploaded.

.. _cmdref_use:

use
---

::

    $ devpi use -h
    usage: devpi use [-h] [--debug] [-y] [-v] [--clientdir DIR] [--set-cfg]
                     [-t {yes,no,auto}] [--always-set-cfg {yes,no}] [--venv VENV]
                     [--urls] [-l] [--delete] [--client-cert pem_file]
                     [url]
    
    show/configure current index and target venv for install activities. This
    shows client-side state, relevant for server interactions, including login
    authentication information, the current remote index (and API endpoints if you
    specify --urls) and the target virtualenv for installation activities.
    
    positional arguments:
      url                   set current API endpoints to the ones obtained from
                            the given url. If already connected to a server, you
                            can specify '/USER/INDEXNAME' which will use the same
                            server context. If you specify the root url you will
                            not be connected to a particular index. If you have a
                            web server with basic auth in front of devpi-server,
                            then use a url like this:
                            https://username:password@example.com/USER/INDEXNAME
    
    optional arguments:
      -h, --help            show this help message and exit
      --set-cfg             create or modify pip/setuptools config files so
                            pip/easy_install will pick up the current devpi index
                            url. If a virtualenv is activated, only its pip config
                            will be set.
      -t {yes,no,auto}, --pip-set-trusted {yes,no,auto}
                            when used in conjunction with set-cfg, also set
                            matching pip trusted-host setting for the provided
                            devpi index url. With 'auto', trusted will be set for
                            http urls or hosts that fail https ssl validation.
                            'no' will clear setting
      --always-set-cfg {yes,no}
                            on 'yes', all subsequent 'devpi use' will implicitely
                            use --set-cfg. The setting is stored with the devpi
                            client config file and can be cleared with '--always-
                            set-cfg=no'.
      --venv VENV           set virtual environment to use for install activities.
                            specify '-' to unset it. venv be created if given name
                            doesn't already exist. Note: an activated virtualenv
                            will be used without needing this.
      --urls                show remote endpoint urls
      -l                    show all available indexes at the remote server
      --delete              delete current association with server
      --client-cert pem_file
                            use the given .pem file as the SSL client certificate
                            to authenticate to the server (EXPERIMENTAL)
    
    generic options:
      --debug               show debug messages including more info on server
                            requests
      -y                    assume 'yes' on confirmation questions
      -v, --verbose         increase verbosity
      --clientdir DIR       directory for storing login and other state

.. _cmdref_user:

user
----

::

    $ devpi user -h
    usage: devpi user [-h] [--debug] [-y] [-v] [--clientdir DIR]
                      [-c | --delete | -m | -l]
                      [username] [keyvalues [keyvalues ...]]
    
    add, remove, modify, list user configuration. This is the central command for
    performing remote user configuration and manipulation. Each indexes (created
    in turn by "devpi index" command) is owned by a particular user. If you create
    a user you either need to pass a ``password=...`` setting or interactively
    type a password.
    
    positional arguments:
      username         user name
      keyvalues        key=value configuration item. Possible keys: email,
                       password and pwhash.
    
    optional arguments:
      -h, --help       show this help message and exit
      -c, --create     create a user
      --delete         delete a user
      -m, --modify     modify user settings
      -l, --list       list user names
    
    generic options:
      --debug          show debug messages including more info on server requests
      -y               assume 'yes' on confirmation questions
      -v, --verbose    increase verbosity
      --clientdir DIR  directory for storing login and other state

.. _`cmdref_devpi_server`:

devpi command reference (server)
================================

::

    $ devpi-server -h
    usage: devpi-server [-h] [-c CONFIGFILE] [--host HOST] [--port PORT]
                        [--threads THREADS]
                        [--max-request-body-size MAX_REQUEST_BODY_SIZE]
                        [--outside-url URL] [--absolute-urls] [--debug]
                        [--profile-requests NUM] [--logger-cfg LOGGER_CFG]
                        [--mirror-cache-expiry SECS] [--replica-max-retries NUM]
                        [--request-timeout NUM] [--offline-mode] [--no-root-pypi]
                        [--replica-file-search-path PATH] [--version]
                        [--role {master,replica,standalone,auto}]
                        [--master-url MASTER_URL] [--replica-cert pem_file]
                        [--gen-config] [--secretfile path] [--requests-only]
                        [--passwd USER] [--serverdir DIR] [--init]
                        [--restrict-modify SPEC] [--keyfs-cache-size NUM]
                        [--root-passwd ROOT_PASSWD]
                        [--root-passwd-hash ROOT_PASSWD_HASH] [--storage NAME]
                        [--export PATH] [--hard-links] [--import PATH]
                        [--no-events] [--start] [--stop] [--status] [--log]
                        [--theme THEME] [--recreate-search-index]
                        [--indexer-backend NAME]
    
    Start a server which serves multiple users and indices. The special root/pypi
    index is a cached mirror of pypi.org and is created by default. All indices
    are suitable for pip or easy_install usage and setup.py upload ...
    invocations.
    
    optional arguments:
      -h, --help            Show this help message and exit.
      -c CONFIGFILE, --configfile CONFIGFILE
                            Config file to use. [None]
    
    web serving options:
      --host HOST           domain/ip address to listen on. Use --host=0.0.0.0 if
                            you want to accept connections from anywhere.
                            [localhost]
      --port PORT           port to listen for http requests. [3141]
      --threads THREADS     number of threads to start for serving clients. [50]
      --max-request-body-size MAX_REQUEST_BODY_SIZE
                            maximum number of bytes in request body. This controls
                            the max size of package that can be uploaded.
                            [1073741824]
      --outside-url URL     the outside URL where this server will be reachable.
                            Set this if you proxy devpi-server through a web
                            server and the web server does not set or you want to
                            override the custom X-outside-url header. [None]
      --absolute-urls       use absolute URLs everywhere. This will become the
                            default at some point. [False]
      --debug               run wsgi application with debug logging [False]
      --profile-requests NUM
                            profile NUM requests and print out cumulative stats.
                            After print profiling is restarted. By default no
                            profiling is performed. [0]
      --logger-cfg LOGGER_CFG
                            path to .json or .yaml logger configuration file. If
                            you specify a yaml file you need to have the pyyaml
                            package installed. [None]
      --theme THEME         folder with template and resource overwrites for the
                            web interface [None]
    
    mirroring options:
      --mirror-cache-expiry SECS
                            (experimental) time after which projects in mirror
                            indexes are checked for new releases. [1800]
      --replica-max-retries NUM
                            Number of retry attempts for replica connection
                            failures (such as aborted connections to pypi). [0]
      --request-timeout NUM
                            Number of seconds before request being terminated
                            (such as connections to pypi, etc.). [5]
      --offline-mode        (experimental) prevents connections to any upstream
                            server (e.g. pypi) and only serves locally cached
                            files through the simple index used by pip. [False]
      --no-root-pypi        don't create root/pypi on server initialization.
                            [False]
      --replica-file-search-path PATH
                            path to existing files to try before downloading from
                            master. These could be from a previous replication
                            attempt or downloaded separately. Expects the
                            structure from inside +files. [None]
    
    deployment and data options:
      --version             show devpi_version (5.0.0) [False]
      --role {master,replica,standalone,auto}
                            set role of this instance. The default 'auto' sets
                            'standalone' by default and 'replica' if the --master-
                            url option is used. To enable the replication protocol
                            you have to explicitly set the 'master' role. [auto]
      --master-url MASTER_URL
                            run as a replica of the specified master server [None]
      --replica-cert pem_file
                            when running as a replica, use the given .pem file as
                            the SSL client certificate to authenticate to the
                            server (EXPERIMENTAL) [None]
      --gen-config          (unix only ) generate example config files for
                            nginx/supervisor/crontab/systemd, taking other passed
                            options into account (e.g. port, host, etc.) [False]
      --secretfile path     file containing the server side secret used for user
                            validation. If it does not exist, a random secret is
                            generated on start up and used subsequently.
                            [{serverdir}/.secret]
      --requests-only       only start as a worker which handles read/write web
                            requests but does not run an event processing or
                            replication thread. [False]
      --passwd USER         set password for user USER (interactive) [None]
      --serverdir DIR       directory for server data. [~/.devpi/server]
      --init                initialize devpi-server state in an empty directory
                            (also see --serverdir) [False]
      --restrict-modify SPEC
                            specify which users/groups may create other users and
                            their indices. Multiple users and groups are separated
                            by commas. Groups need to be prefixed with a colon
                            like this: ':group'. By default anonymous users can
                            create users and then create indices themself, but not
                            modify other users and their indices. The root user
                            can do anything. When this option is set, only the
                            specified users/groups can create and modify users and
                            indices. You have to add root explicitely if wanted.
                            [None]
      --keyfs-cache-size NUM
                            size of keyfs cache. If your devpi-server installation
                            gets a lot of writes, then increasing this might
                            improve performance. Each entry uses 1kb of memory on
                            average. So by default about 10MB are used. [10000]
      --root-passwd ROOT_PASSWD
                            initial password for the root user. This option has no
                            effect if the user 'root' already exist. []
      --root-passwd-hash ROOT_PASSWD_HASH
                            initial password hash for the root user. This option
                            has no effect if the user 'root' already exist. [None]
      --storage NAME        the storage backend to use. "pg8000": Postgresql
                            backend, "sqlite": SQLite backend with files on the
                            filesystem, "sqlite_db_files": SQLite backend with
                            files in DB for testing only [None]
    
    serverstate export / import options:
      --export PATH         export devpi-server database state into PATH. This
                            will export all users, indices, release files (except
                            for mirrors), test results and documentation. [None]
      --hard-links          use hard links during export, import or with
                            --replica-file-search-path instead of copying or
                            downloading files. All limitations for hard links on
                            your OS apply. USE AT YOUR OWN RISK [False]
      --import PATH         import devpi-server database from PATH where PATH is a
                            directory which was created by a 'devpi-server
                            --export PATH' operation, using the same or an earlier
                            devpi-server version. Note that you can only import
                            into a fresh server state directory (positional
                            argument to devpi-server). [None]
      --no-events           no events will be run during import, instead they
                            arepostponed to run on server start. This allows much
                            faster start of the server after import, when devpi-
                            web is used. When you start the server after the
                            import, the search index and documentation will
                            gradually update until the server has caught up with
                            all events. [False]
    
    background server (DEPRECATED, see --gen-config to use a process manager from your OS):
      --start               start the background devpi-server [False]
      --stop                stop the background devpi-server [False]
      --status              show status of background devpi-server [False]
      --log                 show logfile content of background server [False]
    
    search indexing:
      --recreate-search-index
                            Recreate search index for all projects and their
                            documentation. This is only needed if there where
                            indexing related errors in a devpi-web release and you
                            want to upgrade only devpi-web without a full devpi-
                            server import/export. Requires --offline option.
                            [False]
      --indexer-backend NAME
                            the indexer backend to use [whoosh]
