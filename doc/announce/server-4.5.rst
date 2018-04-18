devpi-server-4.5.0: update for pypi.org
=======================================

.. _label_server_4_5:

With devpi-server 4.5.0 the default base for the ``root/pypi`` mirror has changed to ``https://pypi.org``.

For existing devpi-server installations the index configuration should be updated from ``https://pypi.python.org``.

The following is an example on how the default ``root/pypi`` index on m.devpi.net would be changed:

.. code:: bash

    devpi use https://m.devpi.net
    devpi login root
    devpi index root/pypi "mirror_web_url_fmt=https://pypi.org/project/{name}/" "mirror_url=https://pypi.org/simple/"

After that the ``mirror_url`` and ``mirror_web_url_fmt`` options should be updated.

- Replace ``https://m.devpi.net`` with the URL to your devpi-server installation.
- Make sure you include the trailing slashes in the URLs to avoid unnecessary redirects.
- If you use the ``--restrict-modify`` option, you need to use a user directly listed in there or belonging to a group that is listed.
- If your PyPI mirror index has a different name, you need to use that in the ``devpi index`` call.


We offer support contracts and thank in particular Dolby Laboratories and
YouGov Inc who funded a lot of the last year's devpi work.

Mail holger at merlinux.eu to discuss support and training options.
