import errno
import os.path
import sys
from execnet.gateway_base import Unserializer, _Serializer
from io import BytesIO

_nodefault = object()


def rename(source, dest):
    try:
        os.rename(source, dest)
    except OSError:
        destdir = os.path.dirname(dest)
        if not os.path.exists(destdir):
            os.makedirs(destdir)
        if sys.platform == "win32" and os.path.exists(dest):
            os.remove(dest)
        os.rename(source, dest)


def loads(data):
    return Unserializer(
        BytesIO(data),
        strconfig=(False, False)).load(versioned=False)


def dumps(obj):
    return _Serializer().save(obj, versioned=False)


def read_int_from_file(path, default=0):
    try:
        with open(path, "rb") as f:
            return int(f.read())
    except IOError:
        return default


def write_int_to_file(val, path):
    tmp_path = path + "-tmp"
    with get_write_file_ensure_dir(tmp_path) as f:
        f.write(str(val).encode("utf-8"))
    rename(tmp_path, path)


def get_write_file_ensure_dir(path):
    try:
        return open(path, "wb")
    except IOError:
        dirname = os.path.dirname(path)
        if not os.path.exists(dirname):
            try:
                os.makedirs(dirname)
            except IOError as e:
                # ignore file exists errors
                # one reason for that error is a race condition where
                # another thread tries to create the same folder
                if e.errno != errno.EEXIST:
                    raise
        return open(path, "wb")


class BytesForHardlink(bytes):
    """ to allow hard links we have to pass the src path of the content """
    devpi_srcpath = None
