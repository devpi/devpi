
.. include:: links.rst

.. _projectstatus:

Project status, roadmap and contact
----------------------------------------

Latest release
++++++++++++++++++++++++++++

As of October 2013, ``devpi-{server,client,common}`` are released as 1.2 
packages under the MIT license.  Around 450 automated tests are passing 
on python2.7 and python3.3 on Ubuntu 12.04 and Windows 7.

Development background and road map
+++++++++++++++++++++++++++++++++++++

The initial devpi efforts were partly funded by a contract between a
geo-distributed company and merlinux_ with Holger Krekel as the lead
developer.  As of October 30th, the `bug tracker has no open bugs <https://bitbucket.org/hpk42/devpi/issues?status=new&status=open>`_.  There are plans to
further improve devpi and collaborate with Donald Stufft who
is working on the warehouse_ and twine_.

**One area that is lacking is the web UI**.  ``devpi-server`` has a 
:doc:`JSON/REST API <curl>` and it should not be hard for a 
frontend-developer or html templating designer to construct 
a nice web UI around it.  and/or a partner to push forward 
with the web UI and design.

.. _contribute:

contact and contribution points
++++++++++++++++++++++++++++++++++

You are very welcome to report issues, discuss or help:

* issues: https://bitbucket.org/hpk42/devpi/issues

* IRC: #devpi on irc.freenode.net.

* repository: https://bitbucket.org/hpk42/devpi

* mailing list: https://groups.google.com/d/forum/devpi-dev

* business inquiries: holger at merlinux.eu.

Known limitations
+++++++++++++++++++++++++

- ``devpi-server`` currently does not follow any FTP links.

Please also checkout the `devpi issue tracker`_ for further info.
