.. _label_userman_indices_chapter:

Creating, configuring and using indices
========================================

.. include:: ../links.rst

.. sidebar:: Summary
    
    This chapter covers index manipulation such as creation, deletion and use.
    
    :Pre-requisite: You must have logged in to a devpi server 
                    (see :ref:`label_userman_devpi_authentication_chapter` for details)


"Use" sub-command
-----------------

When working with devpi, users need to make **use** of an index. The devpi client provides 
the ``use`` sub-command to achieve this purpose::

   $devpi use http://devpi.mydomain:3141/root/pypi
   
where ``http://devpi.mydomain:3141/root/pypi`` is the **url** to a given index defined as:

   current API endpoints to the ones obtained from the given url. If already connected to a server, 
   you can specify '/USER/INDEXNAME' which will use the same server context. If you specify the 
   root url you will not be connected to a particular index.

Creating an Index
-----------------

As explained in the previous chapter, once a new use is logged in, he or she doesn't have any index 
associated to his or her username::

   $ devpi use
   using index:  http://localhost:3141/root/pypi/
   base indices: http://localhost:3141
   no current install venv set
   logged in as: emilie

In order to create an index, use the **index** sub-command. In the example below, we create 
our **emilie/prod** production index::

   $devpi index -c prod bases=/root/pypi volatile=False
   201: created
   
which leads to the following::

   $ devpi getjson /emilie
   {
       "result": {
           "email": "edoe@mydomain.net", 
           "indices": {
               "prod": {
                   "bases": [
                       "/root/pypi"
                   ], 
                   "type": "stage", 
                   "volatile": false
               }
           }, 
           "username": "emilie"
       }, 
       "status": 200, 
       "type": "userconfig"
   }
   
There are two actual parameters (``bases`` and ``volatile``) which are refered in the command 
help as ``[keyvalues [keyvalues ...]]``

Those are passed directly to the server (avoiding any client update) and define the bases (or 
parent for an index) and whether package version can be overriden (volatile). Being a production 
index, the user will want to set this to False. 

:note: While it is possible to create an infinity of indices for a user, this number should to keep 
       to a minimum. As explained in :ref:`label_userman_concepts_chapter`, it is often 
       preferable to modify the bases of an existing index to say work on a package from 
       another user rather than creating a new one. 
       
       A typical use would be to have a user **production** index ``prod`` which contains package that 
       are fully tested and eventually ready to be released and a **development** or sandbox index 
       ``dev`` which is used to upload packages currently in the works. 
       
Once an index is created, it inherits the packages from its bases::

   $ devpi use  http://localhost:3141/emilie/prod
   using index:  http://localhost:3141/emilie/prod/
   base indices: http://localhost:3141/root/pypi/
   no current install venv set
   logged in as: emilie
   
The development index can be created using **/emilie/prod** as its base::

   $ devpi index -c dev bases=/emilie/prod volatile=True
   201: Created
   $ devpi use  http://localhost:3141/emilie/dev
   using index:  http://localhost:3141/emilie/dev/
   base indices: http://localhost:3141/emilie/prod/
   no current install venv set
   logged in as: emilie
   
which leads to::

   devpi getjson /emilie
   {
       "result": {
           "email": "edoe@mydomain.net", 
           "indices": {
               "dev": {
                   "bases": [
                       "/emilie/prod"
                   ], 
                   "type": "stage", 
                   "volatile": true
               }, 
               "prod": {
                   "bases": [
                       "/root/pypi"
                   ], 
                   "type": "stage", 
                   "volatile": false
               }
           }, 
           "username": "emilie"
       }, 
       "status": 200, 
       "type": "userconfig"
   }
   
Modifying an Index
------------------

It is possible to modify an index. This should be use to change the bases of a given index. 
For instance, the :ref:`label_userman_indices_section` section shows two users 
(emilie and sophie) having each a **prod** and **dev** index. 

Lets now assume that Sophie uploads her ``pysober`` package in her **dev** index and 
Emilie wants to test the integration of this package with the package she is currently 
working on.

An easy way to do this is to specify **/sophie/dev** as a base of **/emilie/dev** using 
the **index** sub-command as follow:

   First, we note that **/emilie/dev** has a single base (**/root/dev**)::
   
      $ devpi getjson http://localhost:3141/emilie/dev
      {
          "result": {
              "bases": [
                  "/emilie/prod"
              ], 
              "type": "stage", 
              "volatile": true
          }, 
          "status": 200, 
          "type": "indexconfig"
      }

   We add **/sophie/dev** as a base to **/emilie/dev**::
   
      $ devpi index --modify /emilie/dev bases=/root/dev bases=/sophie/dev
      201: Created
   
   :note: It is important to specify all bases for that index, that is repeating **/root/dev**
          which can be obtained by doing ``devpi getjson http://localhost:3141/emilie/dev``
          
   From there, Emilie can install ``pysober`` by refering to her own index alone. When the 
   work is done, this relationship can be revoked by doing [#f1]_ ::
   
      $ devpi index --modify /emilie/dev bases=/root/dev
      201: Created
      
      $ devpi getjson http://localhost:3141/emilie/dev
      {
          "result": {
              "bases": [
                  "/root/dev"
              ], 
              "type": "stage", 
              "volatile": true
          }, 
          "status": 200, 
          "type": "indexconfig"
      }
      
   
   
Switching Between Indices
-------------------------

Now that we have two indices, we can switch between them by doing::

   $ devpi use http://localhost:3141/emilie/prod
   automatically starting devpi-server for http://localhost:3141
   using index:  http://localhost:3141/emilie/prod/
   base indices: http://localhost:3141/root/pypi/
   ...
   $ devpi use
   using index:  http://localhost:3141/emilie/prod/
   base indices: http://localhost:3141/root/pypi/
   ...
   $ devpi use http://localhost:3141/emilie/dev
   using index:  http://localhost:3141/emilie/dev/
   base indices: http://localhost:3141/emilie/prod/
   ...
   $ devpi use
   using index:  http://localhost:3141/emilie/dev/
   base indices: http://localhost:3141/emilie/prod/

Deleting an Index
-----------------

:attention: Proceed with care as deleting an index can not be undone. 

In the example below, we create a "bad" index and delete it::

   $ devpi index -c oups bases=/emilie/prod volatile=True

   $ devpi getjson /emilie/oups
   {
       "result": {
           "bases": [
               "/emilie/prod"
           ], 
           "type": "stage", 
           "volatile": true
       }, 
       "status": 200, 
       "type": "indexconfig"
   }
   
   $ devpi index --delete /emilie/oups
   201: index emilie/oups deleted
   
   $ devpi use
   GET http://localhost:3141/emilie/oups/+api
   404: index emilie/oups does not exist
   

   $ devpi getjson /emilie/oups
   {
       "status": 200
   }

.. rubric:: Footnotes

.. [#f1] Make sure that you specify all bases needed with the ``--modify`` option. 




   

