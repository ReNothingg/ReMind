import hashlib
import re
import time
from contextlib import contextmanager, nullcontext
from functools import lru_cache
from threading import Event, Lock, Thread

import redis

CANCEL_TIMEOUT = 900
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,100}")
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
CANCEL_TOKEN = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")


class GenerationStopped(RuntimeError):
    pass


class GenerationControl:
    def __init__(self, *, time_limit=None):
        self.stopped = Event()
        self._lock = Lock()
        self._interrupts = set()
        self.deadline = time.monotonic() + time_limit if time_limit is not None else None

    def check(self):
        if self.stopped.is_set() or (self.deadline is not None and time.monotonic() >= self.deadline):
            raise GenerationStopped("generation_stopped")

    def timeout(self, default):
        self.check()
        if self.deadline is None:
            return default
        return max(0.1, min(default, self.deadline - time.monotonic()))

    def stop(self):
        with self._lock:
            if self.stopped.is_set():
                return
            self.stopped.set()
            callbacks = tuple(self._interrupts)

        def interrupt():
            for callback in callbacks:
                try:
                    callback()
                except (OSError, ValueError, RuntimeError):
                    pass

        if callbacks:
            Thread(target=interrupt, daemon=True).start()

    @contextmanager
    def track(self, callback):
        with self._lock:
            self.check()
            self._interrupts.add(callback)
        try:
            yield
        finally:
            with self._lock:
                self._interrupts.discard(callback)


def interruptible(control, callback):
    return control.track(callback) if control is not None else nullcontext()


def stop_http_stream(response):
    raw = response.raw
    if shutdown := getattr(raw, "shutdown", None):
        shutdown()
    else:
        raw.close()


def cancellable_events(events, control, interrupt):
    with interruptible(control, interrupt):
        for event in events:
            if control is not None:
                control.check()
            yield event


def generation_scope(owner, session_id, request_id, token):
    if not all(isinstance(value, str) for value in (session_id, request_id, token)):
        return None
    if not (
        SESSION_ID.fullmatch(session_id)
        and REQUEST_ID.fullmatch(request_id)
        and CANCEL_TOKEN.fullmatch(token)
    ):
        return None
    digest = hashlib.sha256(f"{owner}\0{session_id}\0{request_id}\0{token}".encode()).hexdigest()
    return "remind:chat:cancel:" + digest


@lru_cache(maxsize=4)
def chat_redis_client(redis_url):
    return redis.Redis.from_url(redis_url, socket_connect_timeout=0.35, socket_timeout=0.45)


def request_cancellation(redis_url, scope):
    if not redis_url:
        return False
    try:
        return bool(chat_redis_client(redis_url).set(scope, "1", ex=CANCEL_TIMEOUT))
    except redis.RedisError:
        return False


@contextmanager
def observe_cancellation(redis_url, scope, control=None):
    control = control or GenerationControl()
    done = Event()
    if redis_url and scope:
        client = chat_redis_client(redis_url)

        def requested():
            try:
                return bool(client.get(scope))
            except redis.RedisError:
                return False

        def watch():
            while not done.wait(0.35):
                if requested():
                    control.stop()
                    return

        if requested():
            control.stop()
        else:
            Thread(target=watch, daemon=True).start()
    try:
        yield control
    finally:
        done.set()
