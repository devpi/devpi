Quickstart for deploying devpi in your company
==============================================

.. include:: links.rst

This quickstart document walks you through setting up your
own ``devpi-server`` instance and creating users
and indices using the ``devpi`` command line client.

Installing devpi-server
-----------------------

Install ``devpi-server``::

    $ pip install -U -q devpi-server

And let's check the version::

    $ devpi-server --version
    0.9.4

.. _gendeploy:

generating a pre-configured server virtualenv directory
-------------------------------------------------------

devpi-server provides the ``--gendeploy`` option to create virtualenv-based
supervisor_-controled deployments of ``devpi-server``.  Even if you
plan on using your own deployment scheme, this option might be interesting
because it creates nginx_ and ``crontab`` config files for your perusal.
Let's make sure we have a recent ``virtualenv`` installed:

    $ pip install -q -U virtualenv

Now, let's create a self-contained virtualenv directory where devpi-server is
configured to run under supervisor_ control.  We can also specify a
particular port to distinguish it from the :ref:`single laptop
deployment (Quickstart) <quickstart-releaseprocess>`::

    $ devpi-server --gendeploy=targetdir --port 4040
    detected existing devpi-ctl, ensuring it is shut down
    Shut down
    restarted /home/hpk/p/devpi/doc/targetdir/bin/supervisord
    using supervisor config: /home/hpk/p/devpi/doc/targetdir/etc/supervisord.conf
    re-installing virtualenv to /home/hpk/p/devpi/doc/targetdir
    Using real prefix '/usr'
    New python executable in /home/hpk/p/devpi/doc/targetdir/bin/python
    Please make sure you remove any previous custom paths from your /home/hpk/.pydistutils.cfg file.
    Installing Setuptools.............................................................................................done.
    Installing Pip....................................................................................................................................done.
    installing devpi-server and supervisor
    Requirement already satisfied (use --upgrade to upgrade): devpi-server>=0.9.4 in ./targetdir/lib/python2.7/site-packages
    Requirement already satisfied (use --upgrade to upgrade): supervisor in ./targetdir/lib/python2.7/site-packages
    Requirement already satisfied (use --upgrade to upgrade): py>=1.4.15 in ./targetdir/lib/python2.7/site-packages (from devpi-server>=0.9.4)
    Requirement already satisfied (use --upgrade to upgrade): execnet>=1.1 in ./targetdir/lib/python2.7/site-packages (from devpi-server>=0.9.4)
    Requirement already satisfied (use --upgrade to upgrade): requests>=1.2.3 in ./targetdir/lib/python2.7/site-packages (from devpi-server>=0.9.4)
    Requirement already satisfied (use --upgrade to upgrade): itsdangerous>=0.23 in ./targetdir/lib/python2.7/site-packages (from devpi-server>=0.9.4)
    Requirement already satisfied (use --upgrade to upgrade): docutils>=0.11 in ./targetdir/lib/python2.7/site-packages (from devpi-server>=0.9.4)
    Requirement already satisfied (use --upgrade to upgrade): pygments>=1.6 in ./targetdir/lib/python2.7/site-packages (from devpi-server>=0.9.4)
    Requirement already satisfied (use --upgrade to upgrade): bottle>=0.11.6 in ./targetdir/lib/python2.7/site-packages (from devpi-server>=0.9.4)
    Requirement already satisfied (use --upgrade to upgrade): setuptools in ./targetdir/lib/python2.7/site-packages (from supervisor)
    Requirement already satisfied (use --upgrade to upgrade): meld3>=0.6.5 in ./targetdir/lib/python2.7/site-packages (from supervisor)
    Cleaning up...
    generating configuration
    creating etc/ directory for supervisor configuration
    wrote /home/hpk/p/devpi/doc/targetdir/etc/supervisord.conf
    wrote /home/hpk/p/devpi/doc/targetdir/etc/nginx-devpi.conf
    wrote /home/hpk/p/devpi/doc/targetdir/bin/devpi-ctl
    wrote /home/hpk/p/devpi/doc/targetdir/bin/devpi-ctl
    created and configured /home/hpk/p/devpi/doc/targetdir
    You may now execute the following:
    
         alias devpi-ctl='/home/hpk/p/devpi/doc/targetdir/bin/devpi-ctl'
    
    and then call:
    
        devpi-ctl start all
    
    after which you can configure pip to always use the default
    root/dev index which carries all pypi packages and the ones
    you upload to it::
    
        # content of $HOME/.pip/pip.conf
        [global]
        index-url = http://localhost:4041/root/dev/+simple/
    
    and/or easy_install and some commands like "setup develop"::
    
        # content of $HOME/.pydistutils.cfg
        [easy_install]
        index_url = http://localhost:4041/root/dev/+simple/
    
    
    
    As a bonus, we have prepared an nginx config at:
    
        /home/hpk/p/devpi/doc/targetdir/etc/nginx-devpi.conf
    
    which you might modify and copy to your /etc/nginx/sites-enabled
    directory.
    
    may quick pypi installations be with you :)

You can now use the ``devpi-ctl`` helper which is a transparent
wrapper of the ``supervisorctl`` tool to make sure that the 
supervisord contained in our ``targetdir`` virtualenv is running::

    $ targetdir/bin/devpi-ctl status 

You could set an alias like this (in your ``.bashrc`` for permanence)::

    alias devpi-ctl=targetdir/bin/devpi-ctl

You now have a tool at your finger tips for controlling 
devpi-server deployment::

    devpi-ctl status    # look at status of devpi-server

    devpi-ctl stop all  # stop all processes

    devpi-ctl start all # start devpi-server 

    devpi-ctl tail devpi-server  # look at current logs
    
    devpi-ctl shutdown  # shutdown all processes including supervisor

    devpi-ctl status    # look at status of devpi processes

You can now uninstall devpi-server from the environment where you
issued ``--gendeploy`` because the ``targetdir`` environment is 
self-contained and does not depend on the original installation::

    $ pip uninstall devpi-server

Lastly, if you want to have things running at system startup and you are using
a standard cron, a modified copy of your user crontab has been amended which
you may inspect and install with:

    $ crontab targetdir/etc/crontab
    targetdir/etc/crontab: No such file or directory

If you persisted your :ref:`pip/easy_install 
configuration <perminstallindex>`, you will now benefit
from a permanently fast ``pip`` installation experience, including
when on travel with your laptop.

But wait, what if you want to install this on a server in your company?
If you are using nginx_, you may::

    modify and copy TARGETDIR/etc/nginx-devpi.conf to
    /etc/nginx/sites-enabled/

and serve your devpi-server deployment to the whole company
under a nice looking url.

If you look into the ``TARGETDIR/etc/supervisord.conf`` 
and read up on supervisor, you can modify the configuration to your liking.
If you prefer different schemes of deployment you may consider it 
"executable" documentation.

.. _`upgrading gendeploy`:

using gendeploy when upgrading
------------------------------

If you want to upgrade your devpi-server deployment which you previously
did using gendeploy_, you can proceed like this::

    # we assume you are in some virtualenv (not the deployment one)
    # and have created a devpi-ctl alias as advised
    
    pip install -U devpi-server  
    devpi-ctl shutdown
    devpi-server --gendeploy=TARGETDIR [--port=...] 
    devpi-ctl start all 

Note that if you don't shutdown the supervisord, the ``--gendeploy``
command is bound to fail.


.. _auth:

requiring authentication
------------------------

In order to configure authentication you need to install the
``devpi`` command line client::

    pip install devpi-client

By default the root password is empty and we can login::

    $ devpi login root --password=
    Traceback (most recent call last):
      File "/home/hpk/bin/devpi", line 9, in <module>
        load_entry_point('devpi-client==1.0rc2', 'console_scripts', 'devpi')()
      File "/home/hpk/p/devpi/client/devpi/main.py", line 29, in main
        return method(hub, hub.args)
      File "/home/hpk/p/devpi/client/devpi/login.py", line 19, in main
        data = hub.http_api("post", hub.current.login, data, quiet=False)
      File "/home/hpk/p/devpi/client/devpi/main.py", line 113, in http_api
        auth=auth)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/sessions.py", line 324, in request
        prep = req.prepare()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/models.py", line 222, in prepare
        p.prepare_url(self.url, self.params)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/models.py", line 291, in prepare_url
        raise MissingSchema("Invalid URL %r: No schema supplied" % url)
    requests.exceptions.MissingSchema: Invalid URL u'None': No schema supplied

We can now change the password, for example to "123"::

    $ devpi user -m root password=123
    Traceback (most recent call last):
      File "/home/hpk/bin/devpi", line 9, in <module>
        load_entry_point('devpi-client==1.0rc2', 'console_scripts', 'devpi')()
      File "/home/hpk/p/devpi/client/devpi/main.py", line 29, in main
        return method(hub, hub.args)
      File "/home/hpk/p/devpi/client/devpi/user.py", line 47, in main
        return user_modify(hub, username, kvdict)
      File "/home/hpk/p/devpi/client/devpi/user.py", line 25, in user_modify
        hub.http_api("patch", hub.current.get_user_url(user), kvdict)
      File "/home/hpk/p/devpi/client/devpi/main.py", line 113, in http_api
        auth=auth)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/sessions.py", line 324, in request
        prep = req.prepare()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/models.py", line 222, in prepare
        p.prepare_url(self.url, self.params)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/models.py", line 291, in prepare_url
        raise MissingSchema("Invalid URL %r: No schema supplied" % url)
    requests.exceptions.MissingSchema: Invalid URL u'root': No schema supplied

At this point, only root will now be able to upload to ``root/dev`` or
any other ``root/*`` indexes.  Let's check our current index::

    $ devpi use
    not using any server
    no current install venv set

this shows we are logged in as root.

Let's logoff::

    $ devpi logoff
    not logged in

and then register ourselves a new user::

    $ devpi user -c alice password=456  email=alice@example.com
    Traceback (most recent call last):
      File "/home/hpk/bin/devpi", line 9, in <module>
        load_entry_point('devpi-client==1.0rc2', 'console_scripts', 'devpi')()
      File "/home/hpk/p/devpi/client/devpi/main.py", line 29, in main
        return method(hub, hub.args)
      File "/home/hpk/p/devpi/client/devpi/user.py", line 43, in main
        return user_create(hub, username, kvdict)
      File "/home/hpk/p/devpi/client/devpi/user.py", line 21, in user_create
        res = hub.http_api("put", hub.current.get_user_url(user), kvdict)
      File "/home/hpk/p/devpi/client/devpi/main.py", line 113, in http_api
        auth=auth)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/sessions.py", line 324, in request
        prep = req.prepare()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/models.py", line 222, in prepare
        p.prepare_url(self.url, self.params)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/models.py", line 291, in prepare_url
        raise MissingSchema("Invalid URL %r: No schema supplied" % url)
    requests.exceptions.MissingSchema: Invalid URL u'alice': No schema supplied

and login::

    $ devpi login alice --password=456
    Traceback (most recent call last):
      File "/home/hpk/bin/devpi", line 9, in <module>
        load_entry_point('devpi-client==1.0rc2', 'console_scripts', 'devpi')()
      File "/home/hpk/p/devpi/client/devpi/main.py", line 29, in main
        return method(hub, hub.args)
      File "/home/hpk/p/devpi/client/devpi/login.py", line 19, in main
        data = hub.http_api("post", hub.current.login, data, quiet=False)
      File "/home/hpk/p/devpi/client/devpi/main.py", line 113, in http_api
        auth=auth)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/sessions.py", line 324, in request
        prep = req.prepare()
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/models.py", line 222, in prepare
        p.prepare_url(self.url, self.params)
      File "/home/hpk/venv/0/local/lib/python2.7/site-packages/requests/models.py", line 291, in prepare_url
        raise MissingSchema("Invalid URL %r: No schema supplied" % url)
    requests.exceptions.MissingSchema: Invalid URL u'None': No schema supplied

Alice can now create a new ``dev`` index::

    $ devpi index -c dev
    Traceback (most recent call last):
      File "/home/hpk/bin/devpi", line 9, in <module>
        load_entry_point('devpi-client==1.0rc2', 'console_scripts', 'devpi')()
      File "/home/hpk/p/devpi/client/devpi/main.py", line 29, in main
        return method(hub, hub.args)
      File "/home/hpk/p/devpi/client/devpi/index.py", line 76, in main
        return index_create(hub, indexname, kvdict)
      File "/home/hpk/p/devpi/client/devpi/index.py", line 13, in index_create
        url = hub.current.get_index_url(indexname, slash=False)
      File "/home/hpk/p/devpi/client/devpi/use.py", line 148, in get_index_url
        userurl = self.get_user_url()
      File "/home/hpk/p/devpi/client/devpi/use.py", line 139, in get_user_url
        raise ValueError("no current authenticated user")
    ValueError: no current authenticated user

and use it::

    $ devpi use alice/dev
    invalid URL: alice/dev/

Our ``alice/dev`` index derives from ``root/dev`` by default
which in turn derives from ``root/pypi`` which mirrors and caches
all pypi packages.

We can now use it to upload any ``setup.py`` project of ours::

    devpi upload

You can now visit with a Browser the index url shown by 
``devpi use`` but note that the 
:ref:`web UI is quite rough <projectstatus>` as of now.

