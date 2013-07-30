.. _label_userman_devpi_install_chapter:

Package Installation
====================

.. include:: ../links.rst

.. sidebar:: Summary
    
    This chapter ilustrates how to install a open source package as well as a package stored 
    on an internal index. 



Overview
--------

As explained in the :ref:`label_userman_concepts_chapter` chapter, the **/root/pypi** is a special cache to 
http://python.pypi.org. 

This section shows how open source packages (e.g. pytest) can be installed 
using a user index (**/emilie/dev**) which has the following inheritance tree::

      /root/pypi
          ^
          |
      /root/dev
          ^
          |
      /emilie/dev
      
      
Creating a virtual environment
------------------------------

This step is presented here to simply create a sandbox using `virtualenv`_::

   $ devpi install --venv sandbox
   --> $ virtualenv sandbox
   New python executable in sandbox/bin/python
   Installing setuptools............done.
   Installing pip...............done
   
   



