
Implementation notes
========================

mapping external (pypi) links
------------------------------------

The :py:meth:`devpi_server.filestore.Filestore.maplink` method maps external links
to filesystem entries and in turn provides links to these local filesystem
entries in devpi's simple pages.  They are only retrieved upon access of the file
and then are cached to avoid re-fetching them.  If the external simple page specifies
a checksumming algorithm such as md5 or sha256, we preserve it
on the entry and serve it accordingly.  This allows to directly
compare the links provided by devpi-server and the external simple pages.
