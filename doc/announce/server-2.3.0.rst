devpi-server-2.3 release
============================================================================

The devpi-server-2.3 release brings two important changes:

- We don't use the XMLRPC "changelog" interface of pypi.python.org
  anymore.  Instead devpi-server now re-checks with pypi every 30 minutes
  and will serve cached contents in between.  If pypi is not reachable
  and we still have cached contents we continue serving the cached content
  so that we can survive pypi outages.

- we switched to semantic versioning so that only major version number
  increases signal the need for an export/import cycle.  If you have
  a devpi-server-2.2.X installation you are not required to export/import.
  However, there has been a regression with the execnet-1.4.0 release
  which was fixed with the now current execnet-1.4.1 release.  If you
  have freshly setup devpi-server and used execnet-1.4.0 at that time
  you will need to do an export with execnet-1.4.0 and then import 
  with execnet-1.4.1 installed.

Note also that we released new micro releases of devpi-client and devpi-web
which are pure bugfixing releases.

For many more changes and fixes, please see the respective CHANGELOG of the
respective packages.

For docs and quickstart tutorials see http://doc.devpi.net

many thanks to Florian Schulze who any of the new features.  And special
thanks go to the two still unnamed companies who funded major parts of
the above work.

have fun,

holger krekel, merlinux GmbH


2.3.0 (2015-09-10)
------------------

- switched to semantic versioning. Only major revisions will ever require an
  export/import cycle.

- fix issue260: Log identical upload message on level "info"

- Log upload trigger message on level "warn"

- The PyPI changelog isn't watched for changes anymore.
  Instead we cache release data for 30 minutes, this can be adjusted with the
  ``--mirror-cache-expiry`` option.

- fix issue251: Require and validate the "X-DEVPI-SERIAL" from master in
  replica thread

- fix issue258: fix FileReplicationError representation for proper logging

- fix issue256: if a project removes all releases from pypi or the project is
  deleted on pypi, we get a 404 back. In that case we now return an empty list
  of releases instead of returning an UpstreamError.

- Change nginx template to serve HEAD in addition to GET requests of files
  directly instead of proxying to devpi-server

- make keyfs cache size configurable via "--keyfs-cache-size" option and
  increase the default size to improve performance for installations with many
  writes

