devpi-server: lightning-fast pypi.python.org proxy
===============================================================

* issues: https://bitbucket.org/hpk42/devpi-server/issues

* IRC: #pylib on irc.freenode.net.

* repository: https://bitbucket.org/hpk42/devpi-server

* mailing list: https://groups.google.com/d/forum/devpi-dev

``devpi-server`` is an easy-to-use caching proxy server for
pypi.python.org, providing fast and reliable installs when
used by pip or easy_install.  

``devpi-server`` offers features not found in other PyPI proxy servers:

- transparent caching of pypi.python.org index and release files 
  on first access, including indexes and files from 3rd party sites.  
  Automatic updating of cached indexes using using pypi's 
  changelog protocol, making sure you'll always see an up-to-date 
  view of what's available.

- pip/easy_install/buildout are shielded from the typical 
  client-side crawling, thus providing lightning-fast and 
  reliable installation (on second access of a package).
  And repeatable offline installs.

- ``devpi-server --gendeploy=TARGETDIR`` creates a zero-configuration
  deployment for your (unixish) laptop or a server, fully contained in 
  a virtualenv_ directory, controlled by ``TARGETDIR/bin/devpi-ctl``,
  a thin wrapper around a dedicated supervisord_.  You'll also find
  templates for nginx_ and a user crontab to start permanent deployment 
  at system boot time under a nice looking URL.  

To summarize, devpi-server aims to help you and your company handle 
all installation interactions with pypi.python.org in the most
reliable and fastest way possible.  

Getting started, trying it out
-------------------------------

Simply install ``devpi-server`` via for example::

    pip install devpi-server # or
    easy_install devpi-server

Make sure you have the ``redis-server`` binary available and issue::

    devpi-server

after which a http server is running on ``localhost:3141`` and you
can use the following index url with pip or easy_install::

    pip install -i http://localhost:3141/ext/pypi/simple/ ...
    easy_install -i http://localhost:3141/ext/pypi/simple/ ...


.. _`pip configuration`:

permanent pip configuration
--------------------------------

To avoid having to re-type the URL, you can configure pip by setting:

- the index-url entry in your ``$HOME/.pip/pip.conf`` (posix) or 
  ``$HOME/pip/pip.conf`` (windows)::
    
    # content of pip.conf
    [global]
    index-url = http://localhost:3141/ext/pypi/simple/

-  ``export PIP_INDEX_URL=http://localhost:3141/ext/pypi/simple/``
   in your ``.bashrc`` or a system-wide location.


Example timing
----------------

Here is a little screen session when using a fresh ``devpi-server``
instance, installing itself in a fresh virtualenv::

    hpk@teta:~/p/devpi-server$ virtualenv devpi >/dev/null
    hpk@teta:~/p/devpi-server$ source devpi/bin/activate
    (devpi) hpk@teta:~/p/devpi-server$ time pip install -q \
                -i http://localhost:3141/ext/pypi/simple/ devpi-server 

    real 21.971s
    user 1.564s
    system 0.420s

So that took 21 seconds.  Now lets remove the virtualenv, recreate
it and install a second time::

    (devpi) hpk@teta:~/p/devpi-server$ rm -rf devpi
    (devpi) hpk@teta:~/p/devpi-server$ virtualenv devpi  >/dev/null
    (devpi)hpk@teta:~/p/devpi-server$ time pip install -q -i http://localhost:3141/ext/pypi/simple/ devpi-server 

    real 1.716s
    user 1.152s
    system 0.472s

Ok, that was more than 10 times faster.  The install of ``devpi-server``
(0.7) involves five packages btw: ``beautifulsoup4, bottle, py, redis,
requests``.


deploying permanently on your laptop
-----------------------------------------------------------

devpi-server is not only a fast pypi cache but since version 0.8 it
comes with a zero-configuration way to deploy permanently on a
laptop or even a server.  If you type::

    $ devpi-server --gendeploy=TARGETDIR [--port=httpport] [--redisport=port]

You will have a fully self-contained directory (a virtualenv in fact) 
which is configured for supervising a continued run of devpi-server.
If you set an alias like this (in your ``.bashrc`` for permanence)::

    $ alias devpi-ctl=TARGETDIR/bin/devpi-ctl

you have a tool at your finger tips for controlling devpi-server deployment::

    $ devpi-ctl status    # look at status of devpi processes

    $ devpi-ctl stop all  # stop all processes

    $ devpi-ctl start all # start devpi-server and redis-server

    $ devpi-ctl tail devpi-server  # look at current logs

    $ devpi-ctl shutdown  # shutdown all processes including supervisor

In fact, ``devpi-ctl`` is just a thin wrapper around ``supervisorctl``
which picks up the right configuration files and ensures its ``supervisord`` 
instance is running.  

Lastly, if you want to have things running at system startup and you are using
a standard cron, a modified copy of your user crontab has been amended which
you may inspect and install with:

    $ crontab TARGETDIR/etc/crontab

If you prepared your `pip configuration`_, you will now benefit
from a permanently fast ``pip`` installation experience, including
when on travel with your laptop.

But wait, what if you want to install this on a server in your company?
If you are using `nginx_`, you may::

    modify and copy TARGETDIR/etc/nginx-devpi.conf to
    /etc/nginx/sites-enabled/

and serve your devpi-server deployment to the whole company
under a nice looking url.

If you look into the ``TARGETDIR/etc/supervisord.conf`` 
and read up on supervisor, you can modify the configuration to your liking.
If you prefer different schemes of deployment you may consider it 
"executable" documentation.


Compatibility and perequisites
---------------------------------

Other than a few automatically installed python dependencies, 
``devpi-server`` currently requires:

- Unix or Windows.  Windows support is somewhat
  experimental and you need to configure your own deployment.

- ``python2.6`` or ``python2.7``.  

- ``redis-server`` version 2.2 or later.  Earlier versions may or 
  may not work (untested).  By default, devpi-server configures and
  starts its own redis instance.  For this it needs to find a
  ``redis-server`` executable.  On windows it will, in addition to the
  PATH variable, also check for ``c:\\program
  files\redis\redis-server.exe`` which is the default install location for
  the `windows redis fork installer
  <https://github.com/rgl/redis/downloads>`_. 

command line options 
---------------------

A list of all devpi-server options::

    $ devpi-server -h
    Usage: devpi-server [options]
    
    Options:
      -h, --help            show this help message and exit
    
      main options:
        --version           show devpi_version (0.7)
        --datadir=DIR       data directory for devpi-server [~/.devpi/serverdata]
        --port=PORT         port to listen for http requests [3141]
        --redisport=PORT    redis server port number [3142]
        --redismode=auto|manual
                            whether to start redis as a sub process [auto]
        --bottleserver=TYPE
                            bottle server class, you may try eventlet or others
                            [wsgiref]
        --debug             run wsgi application with debug logging
    
      pypi upstream options:
        --pypiurl=url       base url of remote pypi server
                            [https://pypi.python.org/]
        --refresh=SECS      periodically pull changes from pypi.python.org [60]

Project status and next steps
-----------------------------

``devpi-server`` is considered beta because it just saw the first releases
and still needs more diverse testing.

It is tested through tox and has all of its automated pytest suite 
passing for python2.7 and python2.6 on Ubuntu 12.04 and Windows 7.

``devpi-server`` is actively developed and bound to see more releases 
in 2013, in particular for supporting private indexes and a new development
and testing workflow system.  You are very welcome to join, discuss 
and contribute, see the top of of this page for contact channels.

.. _nginx: http://nginx.com/
.. _virtualenv: http://pypi.python.org/pypi/virtualenv
.. _supervisord: http://pypi.python.org/pypi/supervisor
