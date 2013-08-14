Quickstart for central server with multiple users
==========================================================

.. include:: links.rst

This quickstart document walks you through setting up your own
``devpi-server`` instance, controling it with supervisor_ and 
serving it through nginx_ on a unix like system.  It also
shows how to create a first user and index.

Installing devpi-server
-----------------------

Install or upgrade ``devpi-server``::

    $ pip install --pre -U -q devpi-server

And let's check the version::

    $ devpi-server --version
    1.0rc2

.. _gendeploy:

generating a virtualenv and configuration files
-------------------------------------------------------

devpi-server provides the ``--gendeploy`` option to create
virtualenv-based supervisor_-controled deployments of ``devpi-server``.
Let's make sure we have a recent ``virtualenv`` installed:

    $ pip install -q -U virtualenv

Now, let's create a self-contained virtualenv directory where
devpi-server is configured to run under supervisor_ control.
Any :ref:`cmdref_devpi_server` option that we pass along
with a ``--gendeploy`` call will be passed through to the
eventual supervisor-managed devpi-server process. 
Here we just pass it a port to distinguish it from the :ref:`single
laptop deployment (Quickstart) <quickstart-releaseprocess>`::

    $ devpi-server --gendeploy=TARGETDIR --port 4040
    creating virtualenv to /home/hpk/p/devpi/doc/TARGETDIR
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

We are now going through the generated instructions step by step.

devpi-ctl: supervisor wrapper for devpi control
+++++++++++++++++++++++++++++++++++++++++++++++

You can now use the ``devpi-ctl`` helper which is a transparent
wrapper of the ``supervisorctl`` tool to make sure that the 
supervisord contained in our ``targetdir`` virtualenv is running.

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
    not using any index ('index -l' to discover, then 'use NAME' to use one)
    no current install venv set

At this point we have only a root user and a ``root/pypi``
index (see :ref:`using root/pypi index <install first>`).


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
    no current install venv set

Our ``alice/dev`` index derives from ``root/pypi`` by default
which makes all pypi.python.org releases available.

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
