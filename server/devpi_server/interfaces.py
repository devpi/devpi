from contextlib import closing
from zope.interface import Interface
from zope.interface import classImplements
from zope.interface.interface import adapter_hooks
from zope.interface.verify import verifyObject


class IStorageConnection(Interface):
    def db_read_last_changelog_serial():
        """ Return last stored serial.
            Returns -1 if nothing is stored yet. """

    def db_read_typedkey(relpath):
        """ Return key name and serial for given relpath.
            Raises KeyError if not found. """

    def get_changes(serial):
        """ Returns deserialized readonly changes for given serial. """

    def get_raw_changelog_entry(serial):
        """ Returns serializes changes for given serial. """


class IStorageConnection2(IStorageConnection):
    def get_relpath_at(relpath, serial):
        """ Get tuple of (last_serial, back_serial, value) for given relpath
            at given serial.
            Raises KeyError if not found. """


# some adapters for legacy plugins


def unwrap_connection_obj(obj):
    if isinstance(obj, closing):
        obj = obj.thing
    return obj


def get_connection_class(obj):
    return unwrap_connection_obj(obj).__class__


def verify_connection_interface(obj):
    verifyObject(IStorageConnection2, unwrap_connection_obj(obj))


@adapter_hooks.append
def adapt(iface, obj):
    # this is not traditional adaption which would return a new object,
    # but for performance reasons we directly patch the class, so the next
    # time no adaption call is necessary
    if iface is IStorageConnection:
        _obj = unwrap_connection_obj(obj)
        cls = get_connection_class(_obj)
        # any storage connection which needs to be adapted to this
        # interface is a legacy one and we can say that it provides
        # the original interface directly
        classImplements(cls, IStorageConnection)
        # make sure the object now actually provides this interface
        verifyObject(IStorageConnection, _obj)
        return obj
    elif iface is IStorageConnection2:
        from .keyfs import get_relpath_at
        # first make sure the old connection interface is implemented
        obj = IStorageConnection(obj)
        _obj = unwrap_connection_obj(obj)
        cls = get_connection_class(_obj)
        # now add fallback method directly to the class
        cls.get_relpath_at = get_relpath_at
        # and add the interface
        classImplements(cls, IStorageConnection2)
        # make sure the object now actually provides this interface
        verifyObject(IStorageConnection2, _obj)
        return obj
