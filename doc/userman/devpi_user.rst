.. _devpi_um_authentication_chapter:

Authentication and User management
==================================

.. include:: ../links.rst

.. sidebar:: Summary

    This section shows how to register a user of a `devpi`_ server and login

In order to access a devpi server, a user must authenticate against it. 

But before that, users must indicate to the devpi client which server to use::

   $ devpi use  http://localhost:3141
   using server: http://localhost:3141/ (not logged in)
   not using any index ('index -l' to discover, then 'use NAME' to use one)
   no current install venv set

In this case, we do not make use of a particular index [#f1]_. We could however
use the default **root/pypi** index [#f2]_.

The **root/pypi** index is a read only cache of http://python.pypi.org  

Once ``devpi`` uses a server, the server base url is cached on the client side.
For instance, to use the ``pypi`` index, once could issue::

   $devpi use /root/pypi
   using index: http://localhost:3141/root/pypi/ (not logged in)
   no current install venv set
   
More on the use command can be found :ref:`here <devpi_um_indices_use_section>`

*related commands*:
   * :ref:`cmdref_use`
   * :ref:`cmdref_user` 
   * :ref:`cmdref_login`

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
   sophie
   root
   emilie
   
Or inspect the server configuration::

   $ devpi getjson /emilie 
   {
       "result": {
           "email": "edoe@mydomain.net", 
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
   
Attempting to modify a user with the wrong credentials results in an error::

   $ devpi login sophie --password 1234
   logged in 'sophie', credentials valid for 10.00 hours
   
::
   $ devpi user -m emilie email=hijack@email.com
   removed expired authentication information
   PATCH http://localhost:3141/emilie
   401 Unauthorized

Logging Off
-----------

In order to log off from a server, issue::

   $ devpi logoff
   not logged in

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

   $devpi user mistake --delete  
   user deleted: mistake

.. rubric:: Footnotes

.. [#f1] Once logged in, the index will default to /root/dev 
.. [#f2] This is a workaround.
    

