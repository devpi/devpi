from devpi_server.log import threadlog
from devpi_server.log import thread_push_log
from devpi_server.main import fatal
from pluggy import HookimplMarker
from pyramid.events import NewRequest
from pyramid.events import subscriber
import os
import signal
import sys
import threading
import time


hookimpl = HookimplMarker("devpiserver")


@subscriber(NewRequest)
def mysubscriber(event):
    event.request._devpi_debugging_start_time = time.time()
    event.request._devpi_debugging_next_time_delta = 1


@hookimpl
def devpiserver_add_parser_options(parser):
    debugging = parser.addgroup("debugging options")
    debugging.addoption(
        "--debug-keyfs", action="store_true",
        help="enable the +keyfs views")
    debugging.addoption(
        "--debug-poke", action="store_true",
        help="enable poking thread which will periodically log a stack trace "
             "of long running requests and other non sleeping threads")
    debugging.addoption(
        "--debug-signal", action="store_true",
        help="enable USR1 signal handler to log the current stack trace "
             "of each thread")


@hookimpl
def devpiserver_cmdline_run(xom):
    if xom.config.args.debug_poke:
        xom.thread_pool.register(PokingThread(xom))
    if xom.config.args.debug_signal:
        current_handler = signal.getsignal(signal.SIGUSR1)
        if current_handler == signal.SIG_DFL:
            signal.signal(signal.SIGUSR1, show_stacks)
        else:
            fatal(f"Couldn't install USR1 signal handler, because another one is already active: {current_handler}")


@hookimpl
def devpiserver_pyramid_configure(config, pyramid_config):
    pyramid_config.include('devpi_debugging.main')


def includeme(config):
    config.add_route(
        "keyfs",
        "/+keyfs")
    config.add_route(
        "keyfs_changelog",
        "/+keyfs/{serial}")
    config.scan()


def iter_frame_stack_info(frame):
    while frame.f_back:
        co = frame.f_code
        name = co.co_name
        (path, filename) = os.path.split(co.co_filename)
        (path, basename) = os.path.split(path)
        yield (frame, co, name, path, basename, filename)
        frame = frame.f_back


def iter_current_threads(skip_thread_ids):
    frames = sys._current_frames()
    for thread_id, frame in frames.items():
        for f, co, name, path, basename, filename in iter_frame_stack_info(frame):
            if thread_id in skip_thread_ids:
                yield (thread_id, frame, "skipped", None)
                break
            if name == "wait" and filename == "threading.py" and basename.startswith("python"):
                continue
            elif name == "get" and filename == "queue.py" and basename.startswith("python"):
                continue
            elif name == "handler_thread" and filename == "task.py" and basename == "waitress":
                yield (thread_id, frame, "known_waiting", "waitress handler")
            elif name == "select" and filename == "selectors.py" and basename.startswith("python"):
                continue
            elif name == "db_read_last_changelog_serial" and basename == "devpi_server":
                continue
            elif name == "sleep" and filename == "mythread.py" and basename == "devpi_server":
                yield (thread_id, frame, "known_waiting", "mythread sleeping")
            elif name == "wait_tx_serial" and filename == "keyfs.py" and basename == "devpi_server":
                yield (thread_id, frame, "known_waiting", "keyfs wait_tx_serial")
            elif name == "_run_once" and filename == "base_events.py" and basename == "asyncio":
                yield (thread_id, frame, "known_waiting", "asyncio _run_once")
            elif name == "_worker" and filename == "thread.py" and basename == "futures":
                yield (thread_id, frame, "known_waiting", "futures _worker")
            elif name == "poll" and filename == "wasyncore.py" and basename == "waitress":
                yield (thread_id, frame, "known_waiting", "waitress poll")
            elif name in ("process_next", "process_next_errored") and filename == "replica.py" and basename == "devpi_server":
                yield (thread_id, frame, "known_waiting", name)
            else:
                yield (thread_id, frame, "unknown", "unknown")
            break


def show_stacks(signal, stack):
    output = ["=" * 80]
    skip = {threading.get_ident()}
    for thread_id, frame, status, status_src in iter_current_threads(skip):
        if status == "skipped":
            continue
        request = None
        stack = []
        thread_name = f"{thread_id}"
        for f, co, name, path, basename, filename in iter_frame_stack_info(frame):
            info = ""
            if name == "thread_run":
                thread_self = f.f_locals.get('self')
                if thread_self is not None:
                    thread_name = f"{thread_self.__class__.__module__}.{thread_self.__class__.__name__} ({thread_name})"
                # we don't need to go further up the stack
                break
            if name == "invoke_request" and filename == "router.py" and basename == "pyramid":
                request = f.f_locals.get('request')
                # we got the request, so we don't need to go further up the stack
                break
            if name == "run" and filename == "threading.py" and basename.startswith("python"):
                thread_self = f.f_locals.get('self')
                if thread_self is not None:
                    thread_name = thread_self.name
                # we don't need to go further up the stack
                break
            if name == "get_value_at" and filename == "keyfs.py" and basename == "devpi_server":
                info = f"{f.f_locals.get('typedkey')} {f.f_locals.get('at_serial')}"
            if name == "get_changes":
                info = f"{f.f_locals.get('serial')}"
            stack.append(f"    {co.co_filename}:{f.f_lineno} {co.co_name} {info}")
        if status == "known_waiting":
            output.append(f"Thread {thread_name} is waiting ({status_src})")
        else:
            stack = '\n'.join(reversed(stack))
            if request is not None:
                delta = time.time() - request._devpi_debugging_start_time
                stack = stack + f"\n  Request {request.method} {request.url} from {request.client_addr} ({request.user_agent}) running for {delta}"
            output.append(f"Thread {thread_name} is in:\n{stack}")
    print(*output, sep='\n', file=sys.stderr, flush=True)


class PokingThread:
    def __init__(self, xom):
        self.xom = xom
        self.thread_ids = {threading.get_ident()}
        self.thread_names = {}

    def tick(self):
        for thread_id, frame, status, status_src in iter_current_threads(self.thread_ids):
            if status in {"known_waiting", "skipped"}:
                continue
            skipped = False
            request = None
            stack = []
            for f, co, name, path, basename, filename in iter_frame_stack_info(frame):
                if name == "queue_projects" and filename == "whoosh_index.py" and basename == "devpi_web":
                    # found the indexer queuing thread
                    self.thread_ids.add(thread_id)
                    skipped = True
                    break
                if name == "process_next" and filename == "whoosh_index.py" and basename == "devpi_web":
                    # found the indexer thread
                    self.thread_ids.add(thread_id)
                    skipped = True
                    break
                if name == "process_next" and filename == "replica.py" and basename == "devpi_server":
                    # found a file replication thread
                    self.thread_ids.add(thread_id)
                    skipped = True
                    break
                if name == "thread_run":
                    if thread_id not in self.thread_names:
                        thread_self = f.f_locals.get('self')
                        if thread_self is None:
                            self.thread_names[thread_id] = None
                        else:
                            self.thread_names[thread_id] = f"{thread_self.__class__.__module__}.{thread_self.__class__.__name__}"
                    if filename == "replica.py" and basename == "devpi_server":
                        if f.f_locals['self'].__class__.__name__ in {'ReplicaThread', 'InitialQueueThread'}:
                            # found one of the replica threads
                            self.thread_ids.add(thread_id)
                            skipped = True
                    # we don't need to go further up the stack
                    break
                if name == "invoke_request" and filename == "router.py" and basename == "pyramid":
                    request = f.f_locals.get('request')
                    # we got the request, so we don't need to go further up the stack
                    break
                stack.append(f"    {co.co_filename}:{f.f_lineno} {co.co_name}")
            if skipped:
                continue
            stack = '\n'.join(reversed(stack))
            if request is not None:
                delta = time.time() - request._devpi_debugging_start_time
                if delta < request._devpi_debugging_next_time_delta:
                    continue
                next_delta = request._devpi_debugging_next_time_delta * 1.25
                request._devpi_debugging_next_time_delta += next_delta
                stack = stack + f"\n  Next poke in {next_delta} for {request.method} {request.url} from {request.client_addr} ({request.user_agent})"
            thread_name = self.thread_names.get(thread_id)
            if thread_name is None:
                thread_name = f"{thread_id}"
            else:
                thread_name = f"{thread_name} ({thread_id})"
            threadlog.info(f"Thread {thread_name} is in:\n{stack}")

    def thread_run(self):
        self.thread_ids.add(threading.get_ident())
        thread_push_log("[POKE]")
        threadlog.info("Starting poking thread")
        while 1:
            self.thread.sleep(1)
            try:
                self.tick()
            except Exception:
                threadlog.exception("Error in poking thread:")
