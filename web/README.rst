================================================
devpi-web: web interface plugin for devpi-server
================================================

This plugin adds a web interface with search for `devpi-server`_.

.. _devpi-server: https://pypi.org/project/devpi-server/

See https://doc.devpi.net for quickstart and more documentation.


Installation
============

``devpi-web`` needs to be installed alongside ``devpi-server``.

You can install it with::

    pip install devpi-web

There is no configuration needed as ``devpi-server`` will automatically discover the plugin through calling hooks using the setuptools entry points mechanism.


Support
=======

If you find a bug, use the `issue tracker at Github`_.

For general questions use the #devpi IRC channel on `freenode.net`_ or the `devpi-dev@python.org mailing list`_.

For support contracts and paid help contact `merlinux.eu`_.

.. _issue tracker at Github: https://github.com/devpi/devpi/issues/
.. _freenode.net: https://freenode.net/
.. _devpi-dev@python.org mailing list: https://mail.python.org/mailman3/lists/devpi-dev.python.org/
.. _merlinux.eu: https://merlinux.eu
