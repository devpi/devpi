.. _label_userman_concepts_chapter:

Concepts
========

.. include:: ../links.rst

.. sidebar:: Summary

      Overview of the main `devpi`_ design goals and concepts.     

Goals
-----

`devpi`_ goals is to provide a fast and reliable package cache to `pypi`_ as well as mechanism to share
packages, in various states of development, amongst users and developers, prior to pushing to the 
*outside world*.

This implies that users can:
  
   * Work unaffected if Pypi fails
   * store "closed source" packages internally, that can be accessed like any other 
     packages as if they were residing on PyPi.
     
With this understanding, let's go over a short overview of the ``devpi-server`` and ``devpi-client``.

Overview
--------

`devpi`_ consists of two parts:

   - A ``devpi server`` responsible for providing a Pypi index cache and to manager sub-indices.
     The ``devpi server`` is compatible with most python installer tools. 
     
   - The ``devpi client`` provides the user interface (command line) to interface with the ``devpi server``.
   
The ``devpi server`` has a default, read-only, index name **/root/pypi**. When a package is not 
found in the index hierachies, it will will query `pypi`_ in a attempt to locate it. If located, 
the ``devpi server`` will cache all versions of that package, and periodically check the change
logs to determine if new versions have been in released, in which case, the new package versions 
will be automatically downloaded into the server cache.  

.. note: The following chapters mostly decribe the interactions with the ``devpi server`` via the ``devpi client``, 
         but it is important to understand how the server operates in order to use the client properly.
         
.. note: Throughout this document, references to *devpi* impply the ``devpi client`` whereas references to the 
         ``devpi server`` will be explicit.
         
The Devpi Server
++++++++++++++++

The ``devpi-server`` consist of a single process running on a system. The system can be local to your machine or 
on a centralized server. The server, by default, normally listens to port 3141 (PI = **3.141**\592653589793)

By default, the server has one index only:

   - **/root/pypi** is a special index which acts a PyPI cache. This index is read only, that is, not package 
     can be uploaded to that index. 
   - **/root/dev** is the default development index used by the root user. This index is writable [#f1]_.

.. note: (1) 

.. _label_userman_indices_section:

What are Indices?
^^^^^^^^^^^^^^^^^

- An index is a container or repository where you can store packages, test results and documentation. 

- An index derives from one or multiple base indices: 

   For instance, imagine Emilie creates her own production index (called */emilie/prod*) (this index
   should have */root/pypi* index as a base in order to get the Pypi packages (the default base is 
   */root/dev*)) and decide to have a developement index (*/emilie.dev*) which derives from her
   production index (a base). The later is used to upload tempory packages currently under development.
   
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
      
  :note: **Important not about inheritance**:
         
         When inheriting from an index, the package of that index **are not copied** 
         into the child index, making it susceptible to changes in the parent index. 
         When looking for package ``foo``, the **devpi-server** will traverse the 
         inheritance tree if this package is not found in the current index.  

- A index is **volatile** if packages can be overriden with the same version 
  (which would make sense for a developement  index). Otherwise, attempting to 
  *upload* [#f2]_ a package with the same version would result in an error. 
  See the :ref:`non_volatile_indexes` for rules specific to this index type. 
   
- A user can have/create as many indices as he/she wants. 

- A user can use the index from another user as the base for one of her/his index:

   Suppose that Sophie has the same index hierarchy as Emilie (*/sophie/prod* -> */sophie/dev*) 
   but wants to experiment with a package emilie is currently working on and stored in */emilie/dev*, 
   Sophie could create a sub index */sophie/fiddle*, using both his and emilie's dev index [#f3]_,
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
                      "bases": [
                          "/root/pypi"
                      ], 
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
^^^^^^^^^^^^^^^^^^^^

As introduced earlier, a volatile index is an index that can be modified/deleted
at will by its owner. 

A :term:`non volatile index` is an index that can not be modified in a desctructive 
manner. This implies that:

   * A **non volatile index** can not be deleted. 
   * If a project is created, it can not be deleted.
   * If a version is uploaded or pushed, it can not be be removed or overriden. 

Furthermore, a non volatile index **can not** use a volatile index as one of its 
bases.

**Non volatile indexes** should be used as common package repositories between 
user, either for staging or production.
   
Deployment Topologies
^^^^^^^^^^^^^^^^^^^^^

The diagram depicts the topology of a master server as well as their index structures:

.. image:: ../images/devpi-topology.png


.. rubric:: Footnotes

.. [#f1] this is true, when you run devpi and the ``devpi server`` on you local machine. 

.. [#f2] **Uploading** refers to storing a package in an index wheresas **pushing** refers to *transfering* 
         a package from one index to another other. In the example above, Emilie would **upload** package 
         *foo* to */emilie/dev* and later on **push** the package from */emilie/dev* to */emilie/prod*.
         
.. [#f3] A prefered option in this case would be to temporarily modify the base of sophie's dev index:

            ``devpi index -m dev bases=/sophie/prod,/emilie/dev volatile=True``       
         









