from tempfile import SpooledTemporaryFile


# before Python 3.11 some methods were missing
if not hasattr(SpooledTemporaryFile, "readable"):

    def readable(self):
        return self._file.readable()

    SpooledTemporaryFile.readable = readable  # type: ignore[method-assign]

if not hasattr(SpooledTemporaryFile, "readinto"):

    def readinto(self, buffer):
        return self._file.readinto(buffer)

    SpooledTemporaryFile.readinto = readinto  # type: ignore[attr-defined]

if not hasattr(SpooledTemporaryFile, "seekable"):

    def seekable(self):
        return self._file.seekable()

    SpooledTemporaryFile.seekable = seekable  # type: ignore[method-assign]

if not hasattr(SpooledTemporaryFile, "writable"):

    def writable(self):
        return self._file.writable()

    SpooledTemporaryFile.writable = writable  # type: ignore[method-assign]
