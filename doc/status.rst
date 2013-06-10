
.. _projectstatus:

Project status and further developments
----------------------------------------

As of June 2013, around 250 automated tests are passing on
python2.7 and python2.6 on Ubuntu 12.04 and Windows 7.

Both the ``devpi-server`` and the ``devpi`` tools are in beta status
because these are initial releases and more diverse real-life testing is
warranted.  The pre-0.9 releases of devpi-server already helped to iron 
out a number of issues and for the 0.9 transition a lot of effort went 
into making devpi-server work consistently with the new PyPI Content 
Delivery Network (CDN).

The project is partly funded by a contract of a geo-distributed company
with merlinux_ and Holger Krekel as the lead developer.  The project is 
actively developed and bound to see more releases in 2013, in particular 
in these areas:

- bugfixes, maintenance, streamlining
- copying release files between index files and to pypi.python.org 
- better testing workflows
- mirroring between devpi-server instances

**One area that is lacking is the web UI**.  I am looking for a partner
to push forward with the web UI and design.  The server provides a 
nicely evolving :doc:`REST API <curl>`.

You are very welcome to report issues, discuss or help:

* issues: https://bitbucket.org/hpk42/devpi/issues

* IRC: #pylib on irc.freenode.net.

* repository: https://bitbucket.org/hpk42/devpi

* mailing list: https://groups.google.com/d/forum/devpi-dev

