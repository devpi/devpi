.. _label_userman_devpi_miscellaneous_chapter:

Miscellaneous
=============

.. include:: ../links.rst

.. sidebar:: Summary

    Placeholder for miscellaneous information such a debugging techniques, tricks, and perhaps FAQ.

.. _`jenkins integration`:

Configuring Jenkins integration
-------------------------------

devpi-server plugins can trigger external CI servers.

For Jenkins you need to install the ``devpi-jenkins`` plugin. See it's
documentation for details.

Uploading different release file formats
----------------------------------------

You can use the ``--formats`` option to tell "devpi upload" which release files
to build and upload::

    devpi upload --formats=bdist_wheel,sdist.tgz

this will create two release files, a wheel and a source distribution, and upload
them to the current index.  Note that you can create/use a ``setup.cfg`` file
to configure the formats along with your project::

    # content of setup.cfg (residing next to setup.py)
    [bdist_wheel]
    universal = 1

    [devpi:upload]
    formats = bdist_wheel,sdist.tgz

Now, when you do a plain ``devpi upload`` it will use the formats specified
in the ``setup.cfg`` file.


Uploading Sphinx docs
---------------------

If you have `Sphinx-based documentation <http://sphinx-doc.org/>`_ you can
upload the rendered HTML documentation to your devpi server with the following
command::

    devpi upload --with-docs

This will build and upload Sphinx documentation by configuring and running
this command::

    setup.py build_sphinx -E --build-dir $BUILD_DIR \
             upload_docs --upload-dir $BUILD_DIR/html

If you have distutils configured to use a devpi index you can upload
documentation to that index simply by executing::

    python setup.py upload_docs

Once uploaded the documentation will be linked to from the index overview page.
Documentation URLs have the following form::

    http://$DEVPI_URL/$USER/$INDEX/$PACKAGE/$VERSION/+doc/index.html

The ``devpi upload --with-docs`` command may fail with the following error::

    error: invalid command 'build_sphinx'

This probably means you're using an old version of setuptools that doesn't
support the `build_sphinx` command used by devpi, so you need to update
setuptools::

    pip install -U setuptools

If the ``devpi upload --with-docs`` command still fails with the same error
message, maybe you forgot to install Sphinx? In that case::

    pip install sphinx

Bulk uploading release files
----------------------------

If you have a directory with existing package files::

    devpi upload --from-dir PATH/TO/DIR

will recursively collect all archives files, register
and upload them to our local ``testuser/dev`` pypi index.

.. _`configure pypirc`:

Using plain ``setup.py`` for uploading
--------------------------------------

In order for ``setup.py`` to register releases and upload
release files we need to configure our index server in
the ``$HOME/.pypirc`` file::

    # content of $HOME/.pypirc
    [distutils]
    index-servers = ...  # any other index servers you have
        dev

    [dev]
    repository: http://localhost:3141/testuser/dev/
    username: testuser
    password: <YOURPASSWORD>

Now let's go to one of your ``setup.py`` based projects and issue::

    python setup.py sdist upload -r dev

This will upload your ``sdist`` package to the ``testuser/dev`` index,
configured in the ``.pypirc`` file.

If you now use ``testuser/dev`` for installation like this::

    pip install -i http://localhost:3141/testuser/dev/+simple/ PKGNAME

You will install your package including any pypi-dependencies
it might need, because the ``testuser/dev`` index inherits all
packages from the pypi-mirroring ``root/pypi`` index.

.. note::

    If working with multiple indices, it is usually more
    convenient to use :ref:`devpi upload`.
