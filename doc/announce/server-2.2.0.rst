devpi-{server-2.2,web-2.3,client-2.2}: plugins, wheel support, pypi compat
============================================================================

With devpi-server-2.2, devpi-web-2.3, devpi-client-2.2 you'll get a host of fixes 
and improvements as well as some major new features for the private pypi system:

- refined devpi-server plugin architecture based on "pluggy", the plugin and hook
  mechanism factored out from pytest.

- devpi-client "test" now support testing of universal wheels IFF you have have an sdist
  alongside your wheel.  python-specific wheels are not supported at this point.

- devpi client "refresh NAME" allows to force a refresh of a pypi package
  from the command line.

- internal refactorings to allow future pypi compatibility (for when it
  changes to SHA256 checksums).  Also we use SHA256 checksumming ourselves now.

For many more changes and fixes, please see the respective CHANGELOG of the
respective packages.

UPGRADE note: devpi-server-2.2 requires to ``--export`` your 2.1
server state and then using ``--import`` with the new version
before you can serve your private packages through devpi-server-2.2.

For docs and quickstart tutorials see http://doc.devpi.net

many thanks to Florian Schulze who co-implemented many of the new features.
And special thanks go to the two companies who funded major parts of the above work.

have fun,

holger krekel, merlinux GmbH
