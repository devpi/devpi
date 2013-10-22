
.. _`quickstart-server`:

Quickstart: permanent install on server/laptop
==========================================================

.. include:: links.rst

This quickstart document walks you through setting up your own
``devpi-server`` instance, controling it with supervisor_ and 
(optionally) serving it through nginx_ on a unix like system.  It also
shows how to create a first user and index.

Note that the :doc:`the pypi-mirroring quickstart
<quickstart-pypimirror>` already discusses the ``devpi-server
--start|--log|--stop`` background-server control options which you can
use to integrate with existing ``init.d`` or similar infrastructure.

.. note::

    If you intend to package devpi-server yourself
    this quickstart may still be helpful because it
    generates configuration files and discusses options 
    for deployment integration.  Btw, if you create 
    a deb/rpm package, :ref:`please share it <contribute>`.

Installing devpi-server
-----------------------

Install or upgrade ``devpi-server``::

    $ pip install --pre -U -q devpi-server

And let's check the version::

    $ devpi-server --version
    1.1

.. _gendeploy:

generating a deployment
-------------------------------------------------------

devpi-server provides the ``--gendeploy`` option to create
virtualenv-based supervisor_-controled deployments of ``devpi-server``.

creating a virtualenv
+++++++++++++++++++++++++++++++

Let's make sure we have a recent ``virtualenv`` installed:

    $ pip install -q -U virtualenv

Now, let's create a self-contained virtualenv directory where
devpi-server is configured to run under supervisor_ control.
It is a good idea to create the virtualenv directory yourself,
using the python of your choice::

    $ virtualenv -q TARGETDIR

If you don't create it, the next step would automatically
create it.

``--gendeploy``: installing packages and configuration files
------------------------------------------------------------

We can now use the ``--gendeploy TARGETDIR`` option to
install packages and configuration files.  Any 
:ref:`devpi-server option <cmdref_devpi_server>` that we pass along
with a ``--gendeploy`` call will be used for creating
adapted config files. 

Here, we just pass it a port to distinguish it from the :ref:`single
laptop deployment (Quickstart) <quickstart-releaseprocess>`::

    $ devpi-server --gendeploy=TARGETDIR --port 4040
    using existing virtualenv: /home/hpk/p/devpi/doc/TARGETDIR
    installing devpi-server,supervisor,eventlet into virtualenv
    wrote /home/hpk/p/devpi/doc/TARGETDIR/etc/supervisord.conf
    wrote /home/hpk/p/devpi/doc/TARGETDIR/etc/nginx-devpi.conf
    wrote /home/hpk/p/devpi/doc/TARGETDIR/bin/devpi-ctl
    wrote /home/hpk/p/devpi/doc/TARGETDIR/etc/crontab
    created and configured /home/hpk/p/devpi/doc/TARGETDIR
    To control supervisor's deployment of devpi-server set:
    
        alias devpi-ctl='/home/hpk/p/devpi/doc/TARGETDIR/bin/devpi-ctl'
    
    and then start the server process:
    
        devpi-ctl start all
    It seems you are using "cron", so we created a crontab file
     which starts devpi-server at boot. With:
    
        crontab /home/hpk/p/devpi/doc/TARGETDIR/etc/crontab
    
    you should be able to install the new crontab but please check it
    first.
    
    We prepared an nginx configuration at:
    
        /home/hpk/p/devpi/doc/TARGETDIR/etc/nginx-devpi.conf
    
    which you might modify and copy to your /etc/nginx/sites-enabled
    directory.
    
    may quick reliable pypi installations be with you :)

.. note::
    
    devops note: at this point, no server has been started and you
    can look at the generated configuration files and integrate
    them into your own deployment structure.

Let's discuss what we have now step by step.

devpi-ctl: supervisor wrapper for devpi control
+++++++++++++++++++++++++++++++++++++++++++++++

You can use the ``devpi-ctl`` helper which is a transparent
wrapper of the ``supervisorctl`` tool to make sure that the 
supervisord contained in our ``TARGETDIR`` virtualenv is running.

Let's check the status of our new server::

    $ TARGETDIR/bin/devpi-ctl status 
    devpi-server                     STOPPED    Not started
    restarted /home/hpk/p/devpi/doc/TARGETDIR/bin/supervisord
    using supervisor config: /home/hpk/p/devpi/doc/TARGETDIR/etc/supervisord.conf

And then start it::

    $ TARGETDIR/bin/devpi-ctl start devpi-server
    devpi-server: started
    using supervisor config: /home/hpk/p/devpi/doc/TARGETDIR/etc/supervisord.conf

Here are some further (wrapped supervisor) commands::

    devpi-ctl status    # look at status of devpi-server

    devpi-ctl stop all  # stop all processes

    devpi-ctl start all # start devpi-server 

    devpi-ctl tail [-f] devpi-server  # look at current logs
    
    devpi-ctl shutdown  # shutdown all processes including supervisor

    devpi-ctl status    # look at status of devpi processes

Now that we have our "gendeploy" instance running, we can
uninstall devpi-server from the original environment::

    $ pip uninstall -y devpi-server
    Uninstalling devpi-server:
      Successfully uninstalled devpi-server

the supervisor configuration file
+++++++++++++++++++++++++++++++++++

If you have your own server supervisor configuration 
you can take the relevant bit out from the gendeploy-generated 
one::

    $ cat TARGETDIR/etc/supervisord.conf
    [unix_http_server]
    file = %(here)s/../supervisor.socket
     
    [supervisord]
    logfile=/home/hpk/p/devpi/doc/TARGETDIR/log/supervisord.log
    pidfile=/home/hpk/p/devpi/doc/TARGETDIR/supervisord.pid
    logfile_maxbytes=50MB           
    logfile_backups=5 
    loglevel=info           ; info, debug, warn, trace
    redirect_stderr = True
    nodaemon=false          ; run supervisord as a daemon
    minfds=1024             ; number of startup file descriptors
    minprocs=200            ; number of process descriptors
    childlogdir=/home/hpk/p/devpi/doc/TARGETDIR/log   ; where child log files will live
     
    [rpcinterface:supervisor]
    supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface
     
    [supervisorctl]
    serverurl=unix://%(here)s/../supervisor.socket
    
    # if you have a system-wide supervisord installation 
    # you might move the below actual program definitions 
    # to a global /etc/supervisord/conf.d/devpi-server.conf
    
    [program:devpi-server]
    command=/home/hpk/p/devpi/doc/TARGETDIR/bin/devpi-server --port 4040 --serverdir /home/hpk/p/devpi/doc/TARGETDIR/data
    priority=999
    startsecs = 5
    redirect_stderr = True
    autostart=False
    

.. _`configured nginx`:

nginx as frontend
+++++++++++++++++

If you are using nginx_ you can take a look at the created
nginx site config file::

    $ cat TARGETDIR/etc/nginx-devpi.conf
    server {
        server_name localhost;   
        listen 80;
        gzip             on;
        gzip_min_length  2000;
        gzip_proxied     any;
        gzip_types       text/html application/json; 
    
        root /home/hpk/p/devpi/doc/TARGETDIR/data;  # arbitrary for now
        location / {
            proxy_pass http://localhost:4040;
            proxy_set_header  X-outside-url $scheme://$host;
            proxy_set_header  X-Real-IP $remote_addr;
        }   
    } 

Apart from the ``server_name`` setting which you probably
want to adjust, this is a ready-use nginx configuration file.
The "X-outside-url" header dynamically tells the devpi-server
instance under which outside url it is reachable.  This is particuarly
needed when using the :ref:`jenkins integration` but might also
be needed in other occassions in the future.

crontab / start at bootup 
+++++++++++++++++++++++++

Lastly, if you want to have things running at system startup and you are
using a standard cron, a modified copy of your user crontab has been
amended which you may inspect::

    $ cat TARGETDIR/etc/crontab
    @reboot /home/hpk/p/devpi/doc/TARGETDIR/bin/devpi-ctl start all

and install with::

    crontab TARGETDIR/etc/crontab

If you look into the ``TARGETDIR/etc/supervisord.conf`` and read up on
supervisor, you can modify the configuration to your liking.


.. _auth:

Initial user setup (on separate machine)
------------------------------------------

In order to manage users and indices let's install the
``devpi-client`` package::

    $ pip install --pre -U -q devpi-client

You can install this client software on different hosts.

Connecting to the server
++++++++++++++++++++++++++++++++++

If you `configured nginx`_, you can use the ``server_name``
of your nginx configuration for connecting to the server.
For purposes of this tutorial, we use the direct
``http://localhost:4040`` as configured above::

    $ devpi use http://localhost:4040
    using server: http://localhost:4040/ (not logged in)
    no current index: type 'devpi use -l' to discover indices

At this point we have only a root user and a ``root/pypi``
index (see :ref:`using root/pypi index <install_first>`).


setting the root password
++++++++++++++++++++++++++++++++++

The first thing to do is to set a password for the ``root`` user.
For that we first need to login::

    $ devpi login root --password ""
    logged in 'root', credentials valid for 10.00 hours

and can then change it::

    $ devpi user -m root password=123

At this point we don't have any other users::

    $ devpi user -l
    root

As we don't plan to work further with the root user, we can log off::

    $ devpi logoff
    login information deleted

Registering a new user
++++++++++++++++++++++++++++++++

Let's register ourselves a new user::

    $ devpi user -c alice password=456  email=alice@example.com
    user created: alice

and then login::

    $ devpi login alice --password=456
    logged in 'alice', credentials valid for 10.00 hours

Alice can now create a new ``dev`` index::

    $ devpi index -c dev
    dev:
      type=stage
      bases=root/pypi
      volatile=True
      uploadtrigger_jenkins=None
      acl_upload=alice

and use it::

    $ devpi use alice/dev
    using index: http://localhost:4040/alice/dev/ (logged in as alice)

Our ``alice/dev`` index derives from ``root/pypi`` by default
which makes all pypi.python.org releases available.

automatically setting pip/easy_install config files
++++++++++++++++++++++++++++++++++++++++++++++++++++

You can cause devpi to set ``$HOME`` configuration files which will
cause ``pip`` and ``easy_install`` to use our in-use index server::

    $ devpi use --set-cfg alice/dev

This will modify or create common configuration files in your home directory
so that subsequent ``pip`` or ``easy_install`` invocations will work against
the ``user/indexname`` index.   You can configure ``devpi`` to perform
this configuration modification::

    $ devpi use --always-set-cfg=yes

This will imply ``--set-cfg`` on all subsequent ``devpi use ...`` operations.

Installing, uploading, testing and releasing
+++++++++++++++++++++++++++++++++++++++++++++++++

You may now continue with install, test and release activities
as described in the :ref:`release process quickstart <quickstart_release_steps>`.

Stopping the server
++++++++++++++++++++++++++++++++++++++++++

Using devpi-ctl again we can stop the server eventually::

    $ TARGETDIR/bin/devpi-ctl shutdown
    Shut down
    using supervisor config: /home/hpk/p/devpi/doc/TARGETDIR/etc/supervisord.conf

versioning, exporting and importing server state
----------------------------------------------------

.. versionadded:: 1.1

.. note::

    you don't need to perform any explicit data migration if you are 
    using devpi-server as a pure pypi mirror, i.e. not creating
    users or uploading releases to indexes.  devpi-server
    will automatically wipe and re-initialize the pypi cache 
    in case of incompatible internal data-layout changes.

``devpi-server`` maintains its state in a ``serverdir``,
by default in ``$HOME/.devpi/server``, unless you specify
a different location via the ``--serverdir`` option.

You can use the ``--export`` option to dump user and index state
into a directory::

    devpi-server --serverdir ~/.devpi/server --export dumpdir

``dumpdir`` will then contain a ``dataindex.json`` and the
files that comprise the server state.  

Using the same version of ``devpi-server`` or a future release you can
then import this dumped server state::

    devpi-server --serverdir newserver --import dumpdir

This will import the previously exported server dump and
create a new server state structure in the ``newserver`` directory.
You can then run a server from this new state::

    devpi-server --serverdir newserver --port 5000

and check through a browser that all your data got migrated correctly.
Once you are happy you can remove the old serverdir (Default
at ``$HOME/.devpi/server``) 

.. note::

    With version 1.1 users, indices, release files,
    test results and documentation files will be dumped.  
    The ``root/pypi`` pypi-caching index is **not dumped**.
