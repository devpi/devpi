devpi-{server-2.1,web-2.2}: upload history, deploy status, groups 
==================================================================

With devpi-server-2.1 and devpi-web-2.2 you'll get a host of fixes and
improvements as well as some major new features for the private pypi
system:

- upload history: release/tests/doc files now carry metadata for 
  by whom, when and to which index something was uploaded

- deployment status: the new json /+status gives detailed information
  about a replica or master's internal state

- a new authentication hook supports arbitrary external authentication 
  systems which can also return "group" membership information.  An initial
  separately released "devpi-ldap" plugin implements verification accordingly.
  You can specify groups in ACLs with the 
  ":GROUPNAME" syntax.  

- a new "--restrict-modify=ACL" option to start devpi-server such that
  only select accounts can create new or modify users or indexes

For many more changes and fixes, please see the CHANGELOG information below.

UPGRADE note: devpi-server-2.1 requires to ``--export`` your 2.0
server state and then using ``--import`` with the new version
before you can serve your private packages through devpi-server-2.1.

Please checkout the web plugin if you want to have a web interface::

    http://doc.devpi.net/2.1/web.html

Here is a Quickstart tutorial for efficient pypi-mirroring 
on your laptop::    

    http://doc.devpi.net/2.1/quickstart-pypimirror.html                         

And if you want to manage your releases or implement staging
as an individual or within an organisation::                                    

    http://doc.devpi.net/2.1/quickstart-releaseprocess.html                     

If you want to host a devpi-server installation with nginx/supervisor
and access it from clients from different hosts::

    http://doc.devpi.net/2.1/quickstart-server.html                             

More documentation here::

    http://doc.devpi.net/2.1/                                                

many thanks to Florian Schulze who co-implemented many of the new features.
And special thanks go to the two companies who funded major parts 
of the above work.

have fun,

Holger Krekel, merlinux GmbH


devpi-server-2.1.0 (compared to 2.0.6)
----------------------------------------

- make replication more precise: if a file cannot be replicated,
  fail with an error log and try again in a few seconds.
  This helps to maintain a consistent replica and discover 
  the potential remaining bugs in the replication code.

- add who/when metadata to release files, doczips and test results
  and preserve it during push operations so that any such file provides
  some history which can be visualized via the web-plugin.  The metadata
  is also exposed via the json API (/USER/INDEX/PROJECTNAME[/VERSION])

- fix issue113: provide json status information at /+status including roles 
  and replica polling status, UUIDs of the repository. See new
  server status docs for more info.

- support for external authentication plugins: new devpiserver_auth_user 
  hook which plugins can implement for user/password validation and
  for providing group membership.

- support groups for acl_upload via the ":GROUPNAME" syntax. This
  requires an external authentication plugin that provides group
  information.

- on replicas return auth status for "+api" requests 
  by relaying to the master instead of using own key.

- add "--restrict-modify" option to specify users/groups which can create,
  delete and modify users and indices.

- make master/replica configuration more permanent and a bit safer
  against accidental errors: introduce "--role=auto" option, defaulting
  to determine the role from a previous invocation or the presence of the
  "--master-url" option if there was no previous invocation.  Also verify
  that a replica talks to the same master UUID as with previous requests.

- replaced hack from nginx template which abused "try_files" in "location /"
  with the recommended "error_page"/"return" combo.
  Thanks Jürgen Hermann

- change command line option "--master" to "--master-url"

- fix issue97: remove already deprecated --upgrade 
  option in favor of just using --export/--import

- actually store UTC in last_modified attribute of release files instead of
  the local time disguising as UTC.  preserve last_modified when pushing 
  a release.  

- fix exception when a static resource can't be found.

- address issue152: return a proper 400 "not registered" message instead
  of 500 when a doczip is uploaded without prior registration.

- add OSX/launchd example configuration when "--gen-config" is issued.
  thanks Sean Fisk.

- fix replica proxying: don't pass original host header when relaying a
  modifying request from replica to master.

- fix export error when a private project doesnt exist on pypi

- fix pushing of a release when it contains multiple tox results.

- fix "refresh" button on simple pages on replica sites

- fix an internal link code issue possibly affecting strangeness
  or exceptions with test result links

- be more tolerant when different indexes have different project names 
  all mapping to the same canonical project name.

- fix issue161: allow "{pkgversion}" to be part of a jenkins url


devpi-web-2.2.0 (compared to 2.1.6)
----------------------------------------

- require devpi-server >= 2.1.0

- static resources now have a plus in front to avoid clashes with usernames and
  be consistent with how other urls work: "+static/..." and "+theme-static/..."

- adjusted font-sizes and cut-off width of content.

- only show underline on links when hovering.

- make the "description hasn't been rendered" warning stand out.

- version.pt: moved md5 sum from it's own column to the file column below the
  download link

- version.pt: added "history" column showing last modified time and infos
  about uploads and pushes.

- fix issue153: friendly error messages on upstream errors.

- index.pt: show permissions on index page

devpi-client-2.0.3 (compared to 2.0.2)
----------------------------------------

- use default "https://www.python.org/pypi" when no repository is set in .pypirc
  see https://docs.python.org/2/distutils/packageindex.html#the-pypirc-file

- fix issue152: when --upload-docs is given, make sure to first register
  and upload the release file before attempting to upload docs (the latter
  requires prior registration)

- fix issue75: add info about basic auth to "url" option help of "devpi use".

- fix issue154: fix handling of vcs-exporting when unicode filenames are
  present.  This is done by striking our own code in favor of Marius Gedminas' 
  vcs exporting functions from his check-manifest project which devpi-client
  now depends on.  This also adds in support for svn and bazaar in addition
  to the already supported git/hg.

- devpi list: if a tox result does not contain basic information (probably a bug in
  tox) show a red error instead of crashing out with a traceback.

- fix issue157: filtering of tox results started with the oldest ones and
  didn't show newer results if the host, platform and environment were the same.

   


