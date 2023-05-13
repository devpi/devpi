import errno
import os.path
import sys
from . import readonly
from io import BytesIO
from struct import error as struct_error
from struct import pack
from struct import unpack


_nodefault = object()


def rename(source, dest):
    try:
        os.replace(source, dest)
    except OSError:
        destdir = os.path.dirname(dest)
        if not os.path.exists(destdir):
            os.makedirs(destdir)
        if sys.platform == "win32" and os.path.exists(dest):
            os.remove(dest)
        os.replace(source, dest)


FOUR_BYTE_INT_MAX = 2147483647


class DataFormatError(Exception):
    pass


class DumpError(DataFormatError):
    """Error while serializing an object."""


class LoadError(DataFormatError):
    """Error while unserializing an object."""


def load(fp, _from_bytes=int.from_bytes, _unpack=unpack):
    read = fp.read
    stack = []
    stack_append = stack.append
    stack_pop = stack.pop

    def _load_collection(type_):
        length = _from_bytes(read(4), byteorder="big", signed=True)
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
            stack_append(read(_from_bytes(read(4), byteorder="big", signed=True)))
        elif opcode == b'B':  # Channel
            raise NotImplementedError("opcode B for Channel")
        elif opcode == b'C':  # False
            stack_append(False)
        elif opcode == b'D':  # float
            stack_append(_unpack("!d", read(8))[0])
        elif opcode == b'E':  # frozenset
            _load_collection(frozenset)
        elif opcode in (b'F', b'G'):  # int, long
            stack_append(_from_bytes(read(4), byteorder="big", signed=True))
        elif opcode in (b'H', b'I'):  # longint, longlong
            stack_append(int(read(_from_bytes(read(4), byteorder="big", signed=True))))
        elif opcode == b'J':  # dict
            stack_append({})
        elif opcode == b'K':  # list
            stack_append([None] * _from_bytes(read(4), byteorder="big", signed=True))
        elif opcode == b'L':  # None
            stack_append(None)
        elif opcode == b'M':  # Python 2 string
            stack_append(read(_from_bytes(read(4), byteorder="big", signed=True)))
        elif opcode in (b'N', b'S'):  # Python 3 string, unicode
            stack_append(read(_from_bytes(read(4), byteorder="big", signed=True)).decode('utf-8'))
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
            stack_append(complex(_unpack("!d", read(8))[0], _unpack("!d", read(8))[0]))
        else:
            # the typo is also in execnet and we compare execnet output directly
            # in tests, so it needs to be here
            raise LoadError(
                "unkown opcode %r - wire protocol corruption?" % opcode)
    if not stopped:
        raise LoadError("didn't get STOP")
    if len(stack) != 1:
        raise LoadError("internal unserialization error")
    return stack_pop(0)


def loads(data):
    return load(BytesIO(data))


def _dump_tuple(write, obj, _pack=pack):
    for item in obj:
        _dispatch[item.__class__](write, item)
    write(b'@')
    write(_pack("!i", len(obj)))


def _dump_bytes(write, obj, _pack=pack):
    write(b'A')
    write(_pack("!i", len(obj)))
    write(obj)


def _dump_bool(write, obj):
    if obj:
        write(b'R')
    else:
        write(b'C')


def _dump_float(write, obj, _pack=pack):
    write(b'D')
    write(_pack("!d", obj))


def _dump_frozenset(write, obj, _pack=pack):
    for item in obj:
        _dispatch[item.__class__](write, item)
    write(b'E')
    write(_pack("!i", len(obj)))


def _dump_int(write, obj, _pack=pack):
    if obj > FOUR_BYTE_INT_MAX:
        write(b'H')
        s = f"{obj}".encode("ascii")
        write(_pack("!i", len(s)))
        write(s)
    else:
        write(b'F')
        write(_pack("!i", obj))


def _dump_dict(write, obj):
    write(b'J')
    for k, v in obj.items():
        _dispatch[k.__class__](write, k)
        _dispatch[v.__class__](write, v)
        write(b'P')


def _dump_list(write, obj, _pack=pack):
    write(b'K')
    write(_pack("!i", len(obj)))
    for i, v in enumerate(obj):
        _dispatch[i.__class__](write, i)
        _dispatch[v.__class__](write, v)
        write(b'P')


def _dump_none(write, obj):
    write(b'L')


def _dump_str(write, obj, _pack=pack):
    try:
        obj = obj.encode('utf-8')
    except UnicodeEncodeError:
        raise DumpError("strings must be utf-8 encodable")
    write(b'N')
    write(_pack("!i", len(obj)))
    write(obj)


def _dump_set(write, obj, _pack=pack):
    for item in obj:
        _dispatch[item.__class__](write, item)
    write(b'O')
    write(_pack("!i", len(obj)))


def _dump_complex(write, obj, _pack=pack):
    write(b'T')
    write(_pack("!d", obj.real))
    write(_pack("!d", obj.imag))


_dispatch = {
    tuple: _dump_tuple,
    readonly.TupleViewReadonly: _dump_tuple,
    bytes: _dump_bytes,
    bool: _dump_bool,
    float: _dump_float,
    frozenset: _dump_frozenset,
    int: _dump_int,
    dict: _dump_dict,
    readonly.DictViewReadonly: _dump_dict,
    list: _dump_list,
    readonly.ListViewReadonly: _dump_list,
    None.__class__: _dump_none,
    str: _dump_str,
    set: _dump_set,
    readonly.SetViewReadonly: _dump_set,
    complex: _dump_complex}


def _dump(write, obj):
    try:
        _dispatch[obj.__class__](write, obj)
    except struct_error as e:
        val = e.__traceback__.tb_frame.f_locals.get('obj', _nodefault)
        msg = e.args[0]
        if isinstance(val, int) and val > FOUR_BYTE_INT_MAX:
            msg = f"int must be less than {FOUR_BYTE_INT_MAX}"
        raise DumpError(msg)
    except KeyError as e:
        raise DumpError(f"can't serialize {e.args[0]}")
    write(b'Q')


def dump(fp, obj):
    return _dump(fp.write, obj)


class _SizeError(Exception):
    pass


def dumplen(obj, maxlen=None):
    count = 0

    if maxlen is None:
        def write(data):
            nonlocal count
            count += len(data)
    else:
        def write(data):
            nonlocal count
            count += len(data)
            if count > maxlen:
                raise _SizeError

    try:
        _dump(write, obj)
    except _SizeError:
        return None
    else:
        return count


def dumps(obj):
    fp = BytesIO()
    _dump(fp.write, obj)
    return fp.getvalue()


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
        return open(path, "w+b")
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
        return open(path, "w+b")


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
