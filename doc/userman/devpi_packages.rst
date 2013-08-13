.. _label_userman_devpi_install_chapter:

Uploading, testing and pushing packages
=========================================

.. include:: ../links.rst

.. sidebar:: Summary
    
    This chapter ilustrates how to upload, test and :term:`push` a package 
    between indices or to an external index server such as 
    https://pypi.python.org.

XXX Overview
--------------

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
      
      
XXX Creating a virtual environment
-----------------------------------

This step is presented here to simply create a sandbox using `virtualenv`_::

   $ devpi install --venv sandbox
   --> $ virtualenv sandbox
   New python executable in sandbox/bin/python
   Installing setuptools............done.
   Installing pip...............done
   
   



