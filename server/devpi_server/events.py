from .log import threadlog
from .readonly import DictViewReadonly, ensure_deeply_readonly
import attr


class EventListeners:
    def __init__(self):
        self._listeners = {}

    def get_listeners(self):
        result = []
        for listeners in self._listeners.values():
            for listener in listeners:
                result.append(listener)
        return result

    def get_listeners_for(self, event_type):
        result = []
        listeners = self._listeners.get(event_type, ())
        for listener in listeners:
            result.append(listener)
        return result

    def has_listeners_for(self, event_type):
        return event_type in self._listeners

    def register(self, event_type, listener, context="request"):
        self._listeners.setdefault(
            event_type, []).append(listener)


class EventQueue:
    def __init__(self, context, keyfs, listeners):
        self._context = context
        self._keyfs = keyfs
        self._listeners = listeners
        self._events = {}
        self.request = None
        self.commited = None
        self.serial = None

    def has_listeners_for(self, event_type):
        return self._listeners.has_listeners_for(event_type)

    def unsafe_notify(self, event_type, **kwargs):
        listeners = self._listeners.get_listeners_for(event_type)
        if not listeners:
            return
        event = event_type(**kwargs)
        for listener in listeners:
            self._events.setdefault(listener, []).append(event)

    def notify(self, event_type, **kwargs):
        listeners = self._listeners.get_listeners_for(event_type)
        if not listeners:
            return
        # small dance so any items that can't be handled throw a traceback
        # right away and not only when first accessed
        kwargs = DictViewReadonly(dict(ensure_deeply_readonly(kwargs)))
        event = event_type(**kwargs)
        for listener in listeners:
            self._events.setdefault(listener, []).append(event)

    def dispatch(self, exception=None):
        if not self._events:
            return
        with self._keyfs.transaction(write=False, at_serial=self.serial) as tx:
            tx.event_queue = self
            commited = self.commited
            request = self.request
            serial = self.serial
            while self._events:
                (listener, events) = self._events.popitem()
                for event in events:
                    try:
                        listener(
                            event,
                            commited=commited,
                            request=request,
                            serial=serial)
                    except Exception:
                        threadlog.exception("Error handling event %r." % event)


@attr.s(frozen=True)
class Event:
    pass


@attr.s(frozen=True)
class ChangedKeysEvent(Event):
    keys = attr.ib()


@attr.s(frozen=True)
class ChangedProjectVersion(Event):
    pass


@attr.s(frozen=True)
class ChangedUser(Event):
    pass


@attr.s(frozen=True)
class ChangedReleaseFile(Event):
    pass


@attr.s(frozen=True)
class NewProjectVersion(Event):
    pass


@attr.s(frozen=True)
class NewReleaseFile(Event):
    pass


@attr.s(frozen=True)
class NewUser(Event):
    user = attr.ib()


@attr.s(frozen=True)
class UploadEvent(Event):
    relpath = attr.ib()
    index = attr.ib()
    metadata = attr.ib()


class DocumentationUploadEvent(UploadEvent):
    pass


class FileUploadEvent(UploadEvent):
    pass
