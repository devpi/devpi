import errno
import os.path
import sys
from execnet.gateway_base import LoadError, Unserializer, _Serializer
from functools import partial
from io import BytesIO
from struct import unpack

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


# int.from_bytes is slower
def load(fp, _unpack_int4=partial(unpack, "!i"), _unpack_float8=partial(unpack, "!d")):
    read = fp.read
    stack = []
    stack_append = stack.append
    stack_pop = stack.pop

    def _load_collection(type_):
        length = _unpack_int4(read(4))[0]
        if length:
            res = type_(stack[-length:])
            del stack[-length:]
            stack_append(res)
        else:
            stack_append(type_())

    stopped = False
    while True:
        opcode = read(1)
        if not opcode:
            raise EOFError
        if opcode == b'@':  # tuple
            _load_collection(tuple)
        elif opcode == b'A':  # bytes
            stack_append(read(_unpack_int4(read(4))[0]))
        elif opcode == b'B':  # Channel
            raise NotImplementedError("%s" % Unserializer.num2func[opcode])
        elif opcode == b'C':  # False
            stack_append(False)
        elif opcode == b'D':  # float
            stack_append(_unpack_float8(read(8))[0])
        elif opcode == b'E':  # frozenset
            _load_collection(frozenset)
        elif opcode in (b'F', b'G'):  # int, long
            stack_append(_unpack_int4(read(4))[0])
        elif opcode in (b'H', b'I'):  # longint, longlong
            stack_append(int(read(_unpack_int4(read(4))[0])))
        elif opcode == b'J':  # dict
            stack_append({})
        elif opcode == b'K':  # list
            stack_append([None] * _unpack_int4(read(4))[0])
        elif opcode == b'L':  # None
            stack_append(None)
        elif opcode == b'M':  # Python 2 string
            stack_append(read(_unpack_int4(read(4))[0]))
        elif opcode in (b'N', b'S'):  # Python 3 string, unicode
            stack_append(read(_unpack_int4(read(4))[0]).decode('utf-8'))
        elif opcode == b'O':  # set
            _load_collection(set)
        elif opcode == b'P':  # setitem
            try:
                value = stack_pop()
                key = stack_pop()
            except IndexError:
                raise LoadError("not enough items for setitem")
            stack[-1][key] = value
        elif opcode == b'Q':  # stop
            stopped = True
            break
        elif opcode == b'R':  # True
            stack_append(True)
        elif opcode == b'T':  # complex
            stack_append(complex(_unpack_float8(read(8))[0], _unpack_float8(read(8))[0]))
        else:
            raise LoadError(
                "unknown opcode %r - wire protocol corruption?" % opcode)
    if not stopped:
        raise LoadError("didn't get STOP")
    if len(stack) != 1:
        raise LoadError("internal unserialization error")
    return stack_pop(0)


def loads(data):
    return load(BytesIO(data))


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


def buffered_iterator(iterable):
    buffer_size = 65536
    buffer = bytearray(buffer_size)
    buffer_pos = 0
    for chunk in iterable:
        chunk_pos = 0
        chunk_remaining = len(chunk)
        while chunk_remaining:
            buffer_remaining = buffer_size - buffer_pos
            while chunk_remaining and buffer_remaining:
                to_copy = min(chunk_remaining, buffer_remaining)
                buffer[buffer_pos:buffer_pos + to_copy] = chunk[
                    chunk_pos:chunk_pos + to_copy]
                buffer_pos += to_copy
                buffer_remaining -= to_copy
                chunk_pos += to_copy
                chunk_remaining -= to_copy
            if not buffer_remaining:
                yield bytes(buffer)
                buffer_pos = 0
    if buffer_pos:
        yield bytes(buffer[:buffer_pos])


class BytesForHardlink(bytes):
    """ to allow hard links we have to pass the src path of the content """
    devpi_srcpath = None
