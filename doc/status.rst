
.. include:: links.rst

.. _projectstatus:

Project status, roadmap and contact
----------------------------------------

Latest release
++++++++++++++++++++++++++++

As of July 2014, ``devpi-{server,client,web,common}`` are released as 2.0
packages under the MIT license.  Around 750 automated tests are passing 
on python2.6, python2.7 and python3.4 on Ubuntu 12.04 and Windows 7 
against the packages.

Development background and road map
+++++++++++++++++++++++++++++++++++++

The initial devpi efforts were partly funded through commercial contracts
carried out by merlinux_ with Holger Krekel and Florian Schulze as lead
developers.  We aim to further devpi through contracts and payed support
and to also collaborate with Donald Stufft who is working on the
warehouse_ and twine_ projects.   

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

- devpi does not itself manage read-access (all information from a
  devpi-server can be read by whoever has access via http so it's up to
  the admins to implement proper per-organsation restrictions by
  configuring nginx_ or some other web service.

- Please checkout the `devpi issue tracker`_ for much further info.
