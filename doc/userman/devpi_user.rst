.. _devpi_um_authentication_chapter:

Authentication and User management
==================================

.. include:: ../links.rst

Summary
-------

This section shows how to register a user of a `devpi`_ server and login

*related commands*:
  * :ref:`cmdref_use`
  * :ref:`cmdref_user` 
  * :ref:`cmdref_login`

Overview
--------

In order to access a devpi server, a user must authenticate against it. 

But before that, users must indicate to the devpi client which server to use::

   $ devpi use  http://localhost:3141
   using server: http://localhost:3141/ (not logged in)
   no current index: type 'devpi use -l' to discover indices
   venv for install/set commands: /tmp/docenv
   only setting venv pip cfg, no global configuration changed
   /tmp/docenv/pip.conf: no config file exists
   always-set-cfg: no

In this case, we do not make use of a particular index. We could however
use the default **root/pypi** index [#f1]_.

The **root/pypi** index is a read only cache of https://pypi.org

Once ``devpi`` uses a server, the server base url is cached on the client side.
For instance, to use the ``pypi`` index, once could issue::

   $ devpi use /root/pypi
   current devpi index: http://localhost:3141/root/pypi (not logged in)
   supported features: server-keyvalue-parsing
   venv for install/set commands: /tmp/docenv
   only setting venv pip cfg, no global configuration changed
   /tmp/docenv/pip.conf: no config file exists
   always-set-cfg: no
   
More on the use command can be found :ref:`here <devpi_um_indices_use_section>`



Creating a User
---------------

If the do not already have a user ID he or she must create one::

   $ devpi user -c emilie email=edoe@mydomain.net password=1234
   user created: emilie
   
::

   $ devpi user -c sophie email=sober@mydomain.net password=1234
   user created: sophie
   
The user can then be listed::

   $ devpi user -l 
   emilie
   root
   sophie
   
Or inspect the server configuration::

   $ devpi getjson /emilie 
   {
       "result": {
           "created": "2021-05-10T14:44:15Z",
           "email": "edoe@mydomain.net",
           "indexes": {},
           "username": "emilie"
       },
       "type": "userconfig"
   }
   
.. note:: Once logged in, Emilie will need to create an index as none are 
          automatically created. Index creation is covered in the next chapter 
          (:ref:`devpi_um_indices_chapter`)

Logging In
----------
   
::

   $ devpi login emilie --password 1234
   logged in 'emilie' at 'http://localhost:3141/root/pypi', credentials valid for 10.00 hours
   
Once authenticated, the session remains for a period of 10 hours. 

   
Modifying a User
----------------

It is possible to modify the user password, email address, title and/or
description.

First login at the user or root::

   $ devpi login emilie --password 1234
   logged in 'emilie' at 'http://localhost:3141/root/pypi', credentials valid for 10.00 hours
   
Then modify the desired property::

   $ devpi user -m emilie email=emilienew@gmail.com
   /emilie changing email: emilienew@gmail.com
   user modified: emilie
   
Attempting to modify a user with the wrong credentials results in an 401 
(unauthorized) error.

Multiple properties can be changed at once::

   $ devpi user -m emilie title=CTO "description=Has final say"
   /emilie changing description: Has final say
   /emilie changing title: CTO
   user modified: emilie

.. versionadded:: 3.0

The title and description are used by ``devpi-web`` in the main overview page.


Deleting a User
---------------
   
If a user is created by mistake or no longer should have access to the server::

   $ devpi user -c mistake password=1234
   user created: mistake
   
It is possible to delete it, provided the current logged in user as the appropriate 
credentials::

   $ devpi login root --password=
   logged in 'root' at 'http://localhost:3141/root/pypi', credentials valid for 10.00 hours
   
::

   $ devpi user mistake -y --delete  
   About to remove: http://localhost:3141/mistake
   Are you sure (yes/no)? yes (autoset from -y option)
   user deleted: mistake

.. rubric:: Footnotes

.. [#f1] This is a workaround.

.. _devpi_um_restrict_user_creation:

Restricting who can create users
--------------------------------

You can use the ``--restrict-modify`` option of ``devpi-server`` to restrict
who can create, modify and delete users and indices.
