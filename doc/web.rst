Web interface and search
============================

The web interface is distributed as a `separate devpi-web package <https://pypi.python.org/pypi/devpi-web>`_.

It registers :doc:`hooks` via the setuptools entry point mechanism to add a web ui to devpi-server.
It provides navigation and search facilities as well as access to uploaded documentation and tox results.


Navigation
----------------------------------------------------

At the root of your devpi server web interface you get an overview of the existing users and their indices:

.. image:: images/web_root_view.png
   :align: center

The index view shows the latest uploads with their info.
You get links to test results and documentation:

.. image:: images/web_index_view.png
   :align: center

The version view shows you all the details about a certain version. It links the homepage, documentation and tox results:

.. image:: images/web_version_view.png
   :align: center

At the top you get links to the index, the package and the version you are currently in.

You can also show package documentation which is embedded into the navigation:

.. image:: images/web_doc_view.png
   :align: center


Searching metadata and documentation
----------------------------------------------------

With the search at the top you can search packages in various ways.
The detailed help is included in the "How to search?" link in the top right.

Some examples for searches:

 - `pytest` searches everything for pytest
 - `pytest type:page` searches only in documentation pages but in all uploaded documentation
 - `ValueError name:pytest` searches for 'ValueError' in all data and documentation we have on projects named 'pytest'.
 - `name:devpi* path:/fschulze/*` search for packages starting with devpi in anything uploaded by 'fschulze'.
 - `classifiers:'Programming Language :: Python :: 3'` searches for packages with the specified classifier, note the single quotes around the classifier, they are necessary because of the whitespace.
