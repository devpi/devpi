Web interface and search
============================

.. versionadded:: 2.0

The web interface is distributed as a `separate devpi-web package <https://pypi.org/project/devpi-web/>`_ which needs to be installed alongside the
``devpi-server`` package ahead of the first server start.  ``devpi-web`` 
provides navigation and search facilities as well as access to uploaded
documentation and tox based testing results for release files.  Without 
``devpi-web``, the core ``devpi-server`` is fully functional for tool usage
but the web interface will otherwise just display json-type information 
on most urls.

.. note::

    If you have a :doc:`replica` setup you are free to run only a replica
    site with the web interface and run a core ``devpi-server`` without it.

Usage and installation
-------------------------------------------

You can install the web interface with::

    pip install devpi-web

There is no configuration needed as ``devpi-server`` will automatically
discover the web plugin through calling :doc:`hooks <../devguide/hooks>`
using the setuptools entry points mechanism.


Navigation (commented screenshots)
----------------------------------------------------

At the root of your devpi server web interface you get an overview of the existing users and their indices:

.. image:: ../images/web_root_view.png
   :align: center

The index view shows the latest uploads with their info.
You get links to test results and documentation:

.. image:: ../images/web_index_view.png
   :align: center

The version view shows you all the details about a certain version. It links the homepage, documentation and tox results:

.. image:: ../images/web_version_view.png
   :align: center

At the top you get links to the index, the package and the version you are currently in.

You can also show package documentation which is embedded into the navigation:

.. image:: ../images/web_doc_view.png
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

You have to create a folder somewhere containing two subfolders ``static`` and
``templates``. You then have to start devpi-server with the ``--theme`` option
and point it to your theme folder. While working on your theme, it is useful
to set the ``CHAMELEON_RELOAD`` environment variable to ``true``, so templates
are reloaded when they change. This unfortunately only works for modifications,
if you add or remove template files, you have to restart devpi-server.

In devpi-web the templates use chameleon. For a full reference of chameleon
templates, see the `chameleon documentation <http://chameleon.readthedocs.org>`_.

For everything common in templates, macros are used.
The only exception are the ``root_above_user_index_list`` and ``root_below_user_index_list`` macros,
which are only used on the devpi-web root page and are empty by default.
They are provided as convenience,
so you don't have to overwrite the whole root template to add some infos.

If you start devpi-server with the ``--debug-macros`` option,
then you can inspect the HTML of every page and look for the included comments to see where and which macros are used.

To change the logo, you
would put your ``logo.gif`` into the ``static`` folder and create a
``logo.pt`` template with the following content:

.. code-block:: html

  <h1><a href="${request.route_url('root')}"><img src="${request.theme_static_url('logo.gif')}" /></a></h1>

To add your own CSS you would create a ``style.css`` in your ``static`` folder
and it will automatically be added in the HTML ``<head>`` of every page.

The folder structure should now look like this::

  /path/to/your/theme
  ├── static
  │   ├── logo.gif
  │   └── style.css
  └── templates
      └── logo.pt

To add some information on the devpi-web frontpage,
you can overwrite the ``root_above_user_index_list.pt`` and ``root_below_user_index_list.pt`` templates.

As an example with ``root_above_user_index_list``:

.. code-block:: html

  <h1>Internal information</h1>
  <p>This devpi instance is used for packages of Foo Inc.</p>
  <p>The production index is <a href="${request.route_url('/{user}/{index}', user='foo', index='production')}">/foo/production</a>.</p>

Any other template has to be copied verbatim and then modified. If they change
in a future devpi-web release, you have to adjust your modified copy accordingly.

To add your own macro you need to provide a template and a ``theme.toml`` file::

  /path/to/your/theme
  ├── static
  ├── templates
  │    └── mymacro.pt
  └── theme.toml

The ``theme.toml`` file needs to provide a section for your macro and point to the template::

  [macros.mymacro]
  template = "mymacro.pt"

For reference you can see all current template files here:
https://github.com/devpi/devpi/tree/main/web/devpi_web/templates

For a specific version you can use tags, for example:
https://github.com/devpi/devpi/tree/web-5.0.0/web/devpi_web/templates
