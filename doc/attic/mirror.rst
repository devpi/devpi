Quickstart mirroring devpi-server  (DRAFT, XXX)
====================================================

.. include:: links.rst

Mirroring operations plan
------------------------------------------------

- all index manipulations are mirrored.
  mirrors maintain their own /root/pypi data structures?

- all writes through keyfs are put into a numbered replay-log

- a mirroring slave connects via a http streaming endpoint to the replay-log
  and gets updates nearly real-time

- uploads/changes are proxied to the master, and slave waits for the
  changes to propagate back through the replay-log

- login/auth verification always is performed by the master

- the slave only handles install/simple/json read ops directly,
  everything else is proxied


problems
=============

- install operations cause write-ops (/root/pypi).

