
Quickstart devpi-server (standalone)
=====================================

.. include:: links.rst

Getting started with a standalone devpi-server
------------------------------------------------

Install ``devpi-server``::

    pip install devpi-server # or
    easy_install devpi-server

And issue::

    devpi-server

after which a http server is running on ``localhost:3141`` and you
can use the following index url with pip or easy_install::

    pip install -i http://localhost:3141/root/pypi/+simple/ ...
    easy_install -i http://localhost:3141/root/pypi/+simple/ ...

to install your packages as usual.  The first install request 
will be slower than any subsequent ones which just serve from 
the local cache.

uploading to the ``root/dev`` index
--------------------------------------

A default devpi-server serves the ``root/dev`` index which
inherits ``root/pypi`` and thus serves all pypi packages
transparently.  But you can also upload extra packages.  
If you are not using :ref:`devpi commands <devpicommands>`,
then you need to perform a few configurations.  First
you need to register a new index server entry in your 
your ``.pypirc`` file::

    # content of $HOME/.pypirc
    [distutils]
    index-servers = ...  # any other index servers you have
        dev

    [dev]
    repository: http://localhost:3141/root/dev/
    username:  
    password:
    # by default devpi-server requires not auth

Now let's go to one of your ``setup.py`` based projects and issue::

    python setup.py sdist upload -r dev 

This will upload your ``sdist`` package to the ``root/dev`` index,
configured in the ``.pypirc`` file.

If you now use ``root/dev`` for installation like this::

    pip install -i http://localhost:3141/root/dev/+simple/ PKGNAME

You will install your package including any pypi-dependencies 
it might need, because the ``root/dev`` index inherits all
packages from the pypi-mirroring ``root/pypi`` index.

.. note::

   We do not define user/password credentials in the ``.pypirc``
   file because ``devpi-server`` allows upload by anyone as long
   as the ``root`` password is empty.

**What to do next?**:

- :ref:`configure a permanent index for pip and easy_install
  <perminstallindex>` to avoid re-typing long URLs.

- :ref:`advance your setup to require authentication <auth>`

- use :ref:`devpi-server --gendeploy <gendeploy>` to create
  and start a permanent deployment to run devpi-server
  on your laptop or a company server.

- checkout the convenient devpi_ command line client for 
  creating users, indexes and for performing standard uploading, 
  installation and testing activities in conjunction 
  with devpi-server.

- checkout the evolving HTTP REST interface :doc:`curl`

- checkout :ref:`projectstatus`


.. _perminstallindex:

permanent pip configuration
-----------------------------------------------

To avoid having to re-type index URLs, you can configure pip by setting:

- the index-url entry in your ``$HOME/.pip/pip.conf`` (posix) or 
  ``$HOME/pip/pip.conf`` (windows)::
    
    # content of pip.conf
    [global]
    index-url = http://localhost:3141/root/dev/+simple/

-  ``export PIP_INDEX_URL=http://localhost:3141/root/dev/+simple/``
   in your ``.bashrc`` or a system-wide location.


permanent easy_install configuration
-----------------------------------------------

To avoid having to re-type the URL, you can configure ``easy_install`` 
by an entry in the ``$HOME/.pydistutils.cfg`` file::
    
    # content of .pydistutils.cfg
    [easy_install]
    index_url = http://localhost:3141/root/dev/+simple/


.. _gendeploy:

deploying permanently on your laptop
-----------------------------------------------------------

devpi-server comes with a zero-configuration way to deploy permanently on a
laptop or even a server (see `upgrading gendeploy`_).  First, make sure
you can invoke the ``virtualenv`` command::

    virtualenv --version
    1.9.1

after which you can type::

    devpi-server --gendeploy=TARGETDIR [--port=httpport] 

and will have a fully self-contained directory (a virtualenv in fact) 
which is configured for supervising a continued run of devpi-server.
If you set an alias like this (in your ``.bashrc`` for permanence)::

    alias devpi-ctl=TARGETDIR/bin/devpi-ctl

you have a tool at your finger tips for controlling devpi-server deployment::

    devpi-ctl status    # look at status of devpi processes

    devpi-ctl stop all  # stop all processes

    devpi-ctl start all # start devpi-server 

    devpi-ctl tail devpi-server  # look at current logs
    
    devpi-ctl shutdown  # shutdown all processes including supervisor

    devpi-ctl status    # look at status of devpi processes

In fact, ``devpi-ctl`` is just a thin wrapper around ``supervisorctl``
which picks up the right configuration files and ensures its ``supervisord`` 
instance is running.  

You can now uninstall devpi-server from the environment where you
issued ``--gendeploy`` because the target environment is self-contained
and does not depend on the original installation.

Lastly, if you want to have things running at system startup and you are using
a standard cron, a modified copy of your user crontab has been amended which
you may inspect and install with:

    $ crontab TARGETDIR/etc/crontab
    TARGETDIR/etc/crontab: No such file or directory

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
-------------------------------------

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
-----------------------------------------

In order to configure authentication you need to install the
``devpi`` command line client::

    pip install devpi-client

By default the root password is empty and we can login::

    $ devpi login root --password=
    logged in 'root', credentials valid for 10.00 hours

We can now change the password, for example to "123"::

    $ devpi user -m root password=123
    200: OK

At this point, only root will now be able to upload to ``root/dev`` or
any other ``root/*`` indexes.  Let's check our current index::

    $ devpi use
    using index:  http://localhost:3141/alice/dev/
    no current install venv set
    logged in as: root

this shows we are logged in as root.

Let's logoff::

    $ devpi logoff
    login information deleted

and then register ourselves a new user::

    $ devpi user -c alice password=456  email=alice@example.com
    201: Created

and login::

    $ devpi login alice --password=456
    logged in 'alice', credentials valid for 10.00 hours

Alice can now create a new ``dev`` index::

    $ devpi index -c dev
    201: Created

and use it::

    $ devpi use alice/dev
    200: OK
    using index:  http://localhost:3141/alice/dev/
    no current install venv set
    logged in as: alice

Our ``alice/dev`` index derives from ``root/dev`` by default
which in turn derives from ``root/pypi`` which mirrors and caches
all pypi packages.

We can now use it to upload any ``setup.py`` project of ours::

    devpi upload

You can now visit with a Browser the index url shown by 
``devpi use`` but note that the 
:ref:`web UI is quite rough <projectstatus>` as of now.

