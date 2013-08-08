.. _label_userman_devpi_authentication_chapter:

Authentication
==============

.. include:: ../links.rst

.. sidebar:: Summary

    This section shows how to register a user of a `devpi`_ server and login

In order to access a devpi server, a user may authenticate against it. Once authenticated, 
the session remains for a period of 10 hours. 

But before that, users must indicate to the devpi client which server to use::

   $ devpi use  http://localhost:3141
   connected to: http://localhost:3141/
   not using any index (use 'index -l')
   no current install venv set
   not currently logged in

In this case, we do not make use of a particular index [#f1]_. We could however use the default 
**root/pypi** index [#f2]_.

The **root/pypi** index is a read only cache of http://python.pypi.org   

Creating a User
---------------

If the user do not already have a user ID he or she must create one::

   $ devpi user -c emilie email=edoe@mydomain.net password=1234
   201: Created
   
Modifying a User
----------------

It is possible to modify the user password and/or email address::

   $ devpi login emilie --password 1234
   automatically starting devpi-server for http://localhost:3141
   logged in 'emilie', credentials valid for 10.00 hours
   $ devpi user -m emilie password=4567 email=newaddress@gmail.com
   $ devpi getjson http://localhost:3141/emilie
   {
       "result": {
           "email": "newaddress@gmail.com",            
           "username": "emilie"
           ...
       }, 
       "type": "userconfig"
   }
   $ devpi logoff
   login information deleted
   
   $ devpi login emilie --password 1234 # test password change was successful
   POST http://localhost:3141/+login
   401 Unauthorized: user u'emilie' could not be authenticated
   $ devpi login emilie --password 4567
   logged in 'emilie', credentials valid for 10.00 hours

.. note:: In order to modify a user, you must be logged in as root or the user itself.
   
Logging In
----------
   
   
and then login::

   $ devpi login emilie --password 1234
   auto-configuring use of root/dev index
   logged in 'emilie', credentials valid for 10.00 hours
   
Once logged in, Emilie will need to create a index as none are automatically created::

   $ devpi getjson http://localhost:3141/emilie
   {
       "result": {
           "email": "edoe@mydomain.net", 
           "username": "emilie"
       }, 
       "status": 200, 
       "type": "userconfig"
   }
   
Index creation is covered in the next chapter (:ref:`label_userman_indices_chapter`)

Logging Off
-----------

In order to log off from a server, issue::

   $ devpi logoff




.. rubric:: Footnotes

.. [#f1] Once logged in, the index will default to /root/dev 
.. [#f2] This is a workaround.
    

