
improve project lookup with no pypi presence
==============================================

when working with projects that don't have a pypi presence
devpi-server will re-check with pypi every time a simple page 
or index listing is requested.  Rather, devpi-server should
cache the 404 and improve changelog-syncing to invalidate that
cache when the project gets a pypi presence.
