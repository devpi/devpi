"""

basic mechanics for turning a mutable dict/list/seq/tuple
into a readonly view.
"""

import py

_immutable = (py.builtin.text, type(None), int, py.builtin.bytes, float)

def ensure_deeply_readonly(val):
    """ return a recursive readonly-view wrapper around ``val`` in O(1) time.

    If the value is already a read-only view or if it is a deeply immutable
    type return it verbatim.

    If the value is a basic container type return an appropriate
    readonly-view of it.  Item accessing functions will maintain
    the readonly property recursively.
    """
    if isinstance(val, _immutable) or isinstance(val, ReadonlyView):
        return val
    if isinstance(val, dict):
        return DictViewReadonly(val)
    elif isinstance(val, (tuple, list)):
        return SeqViewReadonly(val)
    elif isinstance(val, set):
        return SetViewReadonly(val)
    raise ValueError("don't know how to handle type %r" % type(val))


def get_mutable_deepcopy(val):
    """ return a deep copy of ``val`` so that there is no sharing
    of mutable data between val and the returned copy."""
    if isinstance(val, _immutable):
        return val
    if isinstance(val, ReadonlyView):
        val = val._data
    if isinstance(val, dict):
        return dict((k, get_mutable_deepcopy(v)) for k, v in val.items())
    elif isinstance(val, list):
        return [get_mutable_deepcopy(item) for item in val]
    elif isinstance(val, tuple):
        return tuple(get_mutable_deepcopy(item) for item in val)
    elif isinstance(val, set):
        return set(item for item in val)
    raise ValueError("don't know how to handle type %r" % type(val))


def is_deeply_readonly(val):
    """ Return True if the value is either immutable or a readonly proxy
    (which ensures only reading of data is possible). """
    return isinstance(val, ReadonlyView) or isinstance(val, _immutable)

def is_sequence(val):
    """ Return True if the value is a readonly or normal sequence (list, tuple)"""
    return isinstance(val, (ReadonlyView, list, tuple))


class ReadonlyView(object):
    def __init__(self, data):
        self._data = data

    def __eq__(self, other):
        return self._data == other

    def __ne__(self, other):
        return self._data != other

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return "%s(%s)" %(self.__class__.__name__, repr(self._data))


class DictViewReadonly(ReadonlyView):
    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key):
        return ensure_deeply_readonly(self._data[key])

    def items(self):
        for x, y in self._data.items():
            yield x, ensure_deeply_readonly(y)

    def keys(self):
        return self._data.keys()

    def get(self, key, default=None):
        val = self._data.get(key, default)
        return ensure_deeply_readonly(val)


class SeqViewReadonly(ReadonlyView):
    def __iter__(self):
        for x in self._data:
            yield ensure_deeply_readonly(x)

    def __getitem__(self, key):
        return ensure_deeply_readonly(self._data[key])


class SetViewReadonly(ReadonlyView):
    def __iter__(self):
        return iter(self._data)
