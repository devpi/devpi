.. _label_userman_concepts_chapter:

Concepts
========

.. include:: ../links.rst

Summary
-------

Overview of the main `devpi`_ design goals and concepts.

Goals
-----

`devpi`_ goals are to provide a fast and reliable package cache to `pypi`_ 
as well as a mechanism to share packages, in various states of development, 
amongst users and developers, prior to pushing to the *outside world*.

This implies that users can:
  
   * Work unaffected if PyPI fails
   * store "closed source" packages internally, that can be accessed like 
     any other packages as if they were residing on PyPI.
     
With this understanding, let's go over a short overview of the ``devpi-server``
and ``devpi-client``.

Overview
--------

The `devpi`_ consists of two parts:

   - A ``devpi server`` responsible for providing a PyPI index cache and to manage sub-indices.
     The ``devpi server`` is compatible with most python installer tools. 
     
   - The ``devpi client`` provides the user interface (command line) to interface with the ``devpi server``.
   
The ``devpi server`` has a default, read-only, :term:`index` name **/root/pypi**. When a package is not 
found in the index hierarchy, it will will query `pypi`_ in a attempt to locate it. If located, 
the ``devpi server`` will cache all versions of that package, and periodically check the change
logs to determine if new versions have been in released, in which case, the new package versions 
will be automatically downloaded into the server cache.  

.. note: The following chapters mostly describe the interactions with the ``devpi server`` via the ``devpi client``, 
         but it is important to understand how the server operates in order to use the client properly.
         
.. note: Throughout this document, references to *devpi* impply the ``devpi client`` whereas references to the 
         ``devpi server`` will be explicit.

The diagram depicts the topology of a master server as well as their index structures:

.. image:: ../images/devpi-topology.png
         
         
The Devpi Server
----------------

The ``devpi-server`` consist of a single process running on a system. The system can be local to your machine or 
on a centralized server. The server, by default, normally listens to port 3141 (PI = **3.141**\592653589793)

By default, the server has one :term:`index` only:

   - **/root/pypi** is a special index which acts a PyPI cache. This index is read only, that is, no package 
     can be uploaded to that index.
     
Access Control
--------------

To be documented     

The Devpi Client
----------------

To be documented

.. _label_userman_indices_section:

Indexes
-------

- An :term:`index` is a container or repository where you can store packages, test results and documentation. 

- An index derives from one or multiple base indices: 

   For instance, imagine Emilie creates her own production index (called 
   */emilie/prod*)) and decide to have a 
   development index (*/emilie/dev*) which derives from her production index 
   (a base). The latter is used to upload temporary packages currently under 
   development.
   
   The structure could look something like this:: 
   
      $ devpi getjson http://localhost:3141/emilie
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
                      "bases": [],
                      "type": "stage", 
                      "volatile": false
                  }
              }, 
              "username": "emilie"
          }, 
          "status": 200, 
          "type": "userconfig"
      }
      
  :note: **Important note about inheritance**:
         
         When inheriting from an index, the packages of that index **are not copied** 
         into the child index, making it susceptible to changes in the parent index. 
         When looking for package ``foo``, the **devpi-server** will traverse the 
         inheritance tree if this package is not found in the current index.  

- A index is **volatile** if packages can be overridden with the same version 
  (which would make sense for a development index). Otherwise, attempting to 
  *upload* [#f1]_ a package with the same version would result in an error. 
  See the :ref:`non_volatile_indexes` for rules specific to this index type. 
   
- A user can have/create as many indices as he/she wants. 

- A user can use the index from another user as the base for one of her/his index:

   Suppose that Sophie has the same index hierarchy as Emilie (*/sophie/prod* -> */sophie/dev*) 
   but wants to experiment with a package Emilie is currently working on and stored in */emilie/dev*, 
   Sophie could create a sub index */sophie/fiddle*, using both her and Emilie's dev index [#f2]_,
   which would look like::
   
      $ devpi getjson http://localhost:3141/sophie
      {
          "result": {
              "email": "sober@mydomain.net", 
              "indices": {
                  "dev": {
                      "bases": [
                          "/sophie/prod"
                      ], 
                      "type": "stage", 
                      "volatile": true
                  }, 
                  "fiddle": {
                      "bases": [
                          "/sophie/dev", 
                          "/emilie/dev"
                      ], 
                      "type": "stage", 
                      "volatile": true
                  }, 
                  "prod": {
                      "bases": [], 
                      "type": "stage", 
                      "volatile": false
                  }
              }, 
              "username": "sophie"
          }, 
          "status": 200, 
          "type": "userconfig"
      }
      
.. _non_volatile_indexes:

Non Volatile Indexes
++++++++++++++++++++

As introduced earlier, a volatile index is an index that can be modified/deleted
at will by its owner. 

A :term:`non volatile index` is an index that can not be modified in a destructive 
manner. This implies that:

   * A **non volatile index** can not be deleted. 
   * If a project is created, it can not be deleted.
   * If a version is uploaded or pushed, it can not be be removed or overridden. 

Furthermore, a non volatile index **should not** use a volatile index as
one of its bases.

**Non volatile indexes** should be used as common package repositories between 
users, either for staging or production.

.. _mirror_indexes:

Mirror Indexes
++++++++++++++

These indexes mirror externally stored packages. By default *root/pypi* is such
an index, which mirrors https://pypi.org/simple/.

You can't upload or push any packages to mirror indexes. They update themselves
whenever they are used. For example when you try to install a package via pip.

By default the info for a package is cached for 30 minutes, after that the
original is queried again. This can be adjusted per mirror index.

Package releases are downloaded on demand from the original location and cached
indefinitely from then on.

Mirror indexes can't have bases from which they inherit. They are commonly used
as a base in regular indexes though.

The data produced by exporting the server state doesn't include mirrored
releases, only the settings of the mirror index.

The default settings of *root/pypi* look like this::

      $ devpi index root/pypi
      http://localhost:3141/root/pypi:
        type=mirror
        volatile=False
        custom_data=
        mirror_cache_expiry=1800
        mirror_url=https://pypi.org/simple/
        mirror_web_url_fmt=https://pypi.org/project/{name}/
        title=PyPI

.. _um_concept_server_end_points:

Server End Points
-----------------


   

.. rubric:: Footnotes

.. [#f1] **Uploading** refers to storing a package in an index whereas **pushing** refers to *transferring* 
         a package from one index to another. In the example above, Emilie would **upload** package 
         *foo* to */emilie/dev* and later on **push** the package from */emilie/dev* to */emilie/prod*.
         
.. [#f2] A preferred option in this case would be to temporarily modify the base of sophie's dev index:

            ``devpi index -m dev bases=/sophie/prod,/emilie/dev volatile=True``       






