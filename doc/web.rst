Web interface and search
============================

.. versionadded:: 2.0

The web interface is distributed as a `separate devpi-web package <https://pypi.python.org/pypi/devpi-web>`_ which needs to be installed alongside the
``devpi-server`` package ahead of the first server start.  ``devpi-web`` 
provides navigation and search facilities as well as access to uploaded
documentation and tox based testing results for release files.  Without 
``devpi-web``, the core ``devpi-server`` is fully functional for tool usage
but the web interface will otherwise just display json-type information 
on most urls.

.. note::

    If you have a :doc:`replica` setup you are free to run only a replica
    site with the web interface and run a core ``devpi-server`` without it.

    Note, however, that as of the 2.0 version, you cannot add the web interface
    plugin after the first devpi-server start.  It's recommended to
    install the web interface for devpi-server installations unless you are
    aiming for a more refined deployment aiming at minimizing risks.
    It's fine to uninstall devpi-web later in the lifetime of a devpi-server.

    It is possible to use devpi-web if you run an import though. So if you
    already used devpi-server and want to start using devpi-web, you can do so
    by exporting your data and importing it in an installation that has
    devpi-web included.


Usage and installation
-------------------------------------------

``devpi-web`` needs to be installed alongside ``devpi-server`` before
the server is started the first time because it needs to follow all 
server state changes from the beginning. You can export without devpi-web
and import in a new installation with devpi-web though.

You can install the web interface with::

    pip install devpi-web

There is no configuration needed as ``devpi-server`` will automatically
discover the web plugin through calling :doc:`hooks` using the setuptools
entry points mechanism.


Navigation (commented screenshots)
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


Notes
----------------------------------------------------

The text of the long description of uploaded packages is processed in the same
way as on PyPI. In some cases the first title and subtitle are stripped from
the text. That is also happening on PyPI. For compatibility and to let you
properly test packages before putting them on PyPI we do the same, even though
in our page layout it would make more sense not to strip.


Themes
----------------------------------------------------

It is possible to overwrite templates and macros to customize the look of your
devpi instance.

You have to create a folder containing two subfolders ``static`` and
``templates``. You then have to start devpi-server with the ``--theme`` option
and point it to your theme folder. While working on your theme, it is useful
to set the ``CHAMELEON_RELOAD`` environment variable to ``true``, so templates
are reloaded when they change. This unfortunately only works for modifications,
if you add or remove template files, you have to restart devpi-server.

In devpi-web the templates use chameleon. For a full reference of chameleon
templates, see the `chameleon documentation <http://chameleon.readthedocs.org>`_.

For everything common in templates, macros are used. The only exception are the
``rootaboveuserindexlist`` and ``rootbelowuserindexlist`` macros which are only
used on the devpi-server root page and are empty by default. They are provided
as convenience, so you don't have to overwrite the whole root template to add
some infos.

To change the logo, you
would put your ``logo.gif`` into the ``static`` folder and create a
``macros.pt`` template with the following content:

.. code-block:: xml

  <metal:logo define-macro="logo">
      <h1><a href="${request.route_url('root')}"><img src="${request.theme_static_url('logo.gif')}" /></a></h1>
  </metal:logo>

To add your own CSS you would create a ``style.css`` in your ``static`` folder
and add the following macro in ``macros.pt``:

.. code-block:: xml

  <metal:head define-macro="headcss" use-macro="request.macros['original-headcss']">
      <metal:mycss fill-slot="headcss">
          <link rel="stylesheet" type="text/css" href="${request.theme_static_url('style.css')}" />
      </metal:mycss>
  </metal:head>

In this example we reuse the original ``headcss`` macro, which is available as
``original-headcss`` and only fill it's predefined ``headcss`` slot.

To add some information on the devpi frontpage, you can overwrite the
``rootaboveuserindexlist`` and ``rootbelowuserindexlist`` macros.

.. code-block:: xml

  <metal:info define-macro="rootaboveuserindexlist">
      <h1>Internal information</h1>
      <p>This devpi instance is used for packages of Foo Inc.</p>
      <p>The production index is <a href="${request.route_url('/{user}/{index}', user='foo', index='production')}">/foo/production</a>.</p>
  </metal:info>

Any other template has to be copied verbatim and then modified. If they change
in a future devpi-web release, you have to adjust your modified copy accordingly.

For reference you can see the whole ``macro.pt`` file here:

.. literalinclude:: ../web/devpi_web/templates/macros.pt
  :language: xml
