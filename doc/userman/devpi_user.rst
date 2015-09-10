.. _devpi_um_authentication_chapter:

Authentication and User management
==================================

.. include:: ../links.rst

.. sidebar:: Summary

    This section shows how to register a user of a `devpi`_ server and login
    
    *related commands*:
      * :ref:`cmdref_use`
      * :ref:`cmdref_user` 
      * :ref:`cmdref_login`

In order to access a devpi server, a user must authenticate against it. 

But before that, users must indicate to the devpi client which server to use::

   $ devpi use  http://localhost:3141
   using server: http://localhost:3141/ (not logged in)
   no current index: type 'devpi use -l' to discover indices
   ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
   ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
   ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
   always-set-cfg: no

In this case, we do not make use of a particular index. We could however
use the default **root/pypi** index [#f1]_.

The **root/pypi** index is a read only cache of http://pypi.python.org  

Once ``devpi`` uses a server, the server base url is cached on the client side.
For instance, to use the ``pypi`` index, once could issue::

   $ devpi use /root/pypi
   current devpi index: http://localhost:3141/root/pypi (not logged in)
   ~/.pydistutils.cfg     : http://localhost:4040/alice/dev/+simple/
   ~/.pip/pip.conf        : http://localhost:4040/alice/dev/+simple/
   ~/.buildout/default.cfg: http://localhost:4040/alice/dev/+simple/
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
   test
   sophie
   root
   emilie
   
Or inspect the server configuration::

   $ devpi getjson /emilie 
   {
       "result": {
           "email": "edoe@mydomain.net", 
           "indexes": {}, 
           "username": "emilie"
       }, 
       "type": "userconfig"
   }
   
.. note:: Once logged in, Emilie will need to create a index as none are 
          automatically created. Index creation is covered in the next chapter 
          (:ref:`devpi_um_indices_chapter`)

Logging In
----------
   
::

   $ devpi login emilie --password 1234
   logged in 'emilie', credentials valid for 10.00 hours
   
Once authenticated, the session remains for a period of 10 hours. 

   
Modifying a User
----------------

It is possible to modify the user password and/or email address.

First login at the user or root::

   $ devpi login emilie --password 1234
   logged in 'emilie', credentials valid for 10.00 hours
   
Then modify the desired property::

   $ devpi user -m emilie email=emilienew@gmail.com
   user modified: emilie
   
Attempting to modify a user with the wrong credentials results in an 401 
(unauthorized) error.

Deleting a User
---------------
   
If a user is created by mistake or no longer should have access to the server::

   $ devpi user -c mistake password=1234
   user created: mistake
   
It is possible to delete it, provided the current logged in user as the appropriate 
credentials::

   $ devpi login root --password=
   logged in 'root', credentials valid for 10.00 hours
   
::

   $ devpi user mistake -y --delete  
   About to remove: <URL 'http://localhost:3141/mistake'>
   Are you sure (yes/no)? yes (autoset from -y option)
   user deleted: mistake

.. rubric:: Footnotes

.. [#f1] This is a workaround.
    
Restricting who can create users
--------------------------------

You can use the ``--restrict-modify`` option of ``devpi-server`` to restrict
who can create, modify and delete users and indices.
