Quickstart devpi command line
===================================

.. include:: links.rst

Getting started
-------------------------------

install
++++++++++++++++++++++++

Install ``devpi`` which will pull in the appropriate ``devpi-server`` and 
``devpi-client`` packages::

    pip install devpi
    easy_install devpi

start and connect to server 
+++++++++++++++++++++++++++++

Run a default server instance in one window::

    devpi-server

which will start a default server on ``http://localhost:3141``.

Now let's connect to this default server::

	$ devpi use 

We are now configured to use the ``root/dev`` index on our default
server.  (If your server is elsewhere, just specify an URL after
``devpi use``).

install a package using pip/easy_install
++++++++++++++++++++++++++++++++++++++++++++++

Let's create a virtualenv to install something into::

	$ virtualenv v1

and then install a package into it::

	$ devpi install --venv=v1 pytest

This will invoke pip_ with the right options to install 
the package from our currently used ``root/dev`` index.  
If you want to use ``easy_install`` instead type::

	$ devpi install --easy-install --venv=v1 pytest

In either case, you can invoke the just installed tool
to check it was installed correctly::

	$ v1/bin/py.test --version


Uploading a package
-------------------------

Go to a ``setup.py`` based project and issue::

	devpi upload

This will build an ``sdist`` archive and upload it 
to the ``root/dev`` index.  You can now install your 
freshly uploaded release file::

	$ devpi install --venv=v1 YOUR_PROJECT_NAME

You will install your package including any pypi-dependencies 
it might need, because the ``root/dev`` index inherits all
packages from the pypi-mirroring ``root/pypi`` one.


Testing a package with tox
------------------------------

If you use tox_ and have a ``tox.ini`` in your uploaded project
you can invoke the ``devpi test`` subcommand::

	$ devpi test -e py27 YOUR_PROJECT_NAME

This downloads and unpacks the latest release and 
invokes ``tox -e py27`` for your convenience.

.. ::

	Pushing a package to pypi.org
	----------------------------------------

	Once you determine that a release is ready, you can
	push it to ``pypi.org``::

		$ devpi push PROJ-VERSION 
