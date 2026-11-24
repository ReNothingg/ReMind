import logging
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, Lock

from backend.services.chat.cancellation import GenerationControl, GenerationStopped


@dataclass
class PendingUpdate:
    update: dict
    lane: tuple
    control: GenerationControl = field(default_factory=GenerationControl)
    draft: tuple | None = None
    future: Future | None = None
    done: bool = False


class TelegramUpdates:
    def __init__(self, handle, workers=4):
        self.handle = handle
        self.workers = workers
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="remind-telegram")
        self.pending = OrderedDict()
        self.lanes = {}
        self.signal = Event()
        self.offset = None
        self.control_lock = Lock()
        self.drafts = {}

    def _stop(self, update):
        stopped = update.get("stopped_message_generation")
        if isinstance(stopped, dict):
            key = (
                (stopped.get("chat") or {}).get("id"),
                stopped.get("message_thread_id") or 0,
                stopped.get("draft_id"),
            )
            with self.control_lock:
                control = self.drafts.get(key)
            if control:
                control.stop()
            return True
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if (
            chat.get("type") == "private"
            and chat.get("id") == sender.get("id")
            and str(message.get("text", "")).split("@", 1)[0].strip() == "/stop"
        ):
            with self.control_lock:
                targets = [
                    control
                    for key, control in self.drafts.items()
                    if key[:2] == (chat["id"], message.get("message_thread_id") or 0)
                ]
            for control in targets:
                control.stop()
        return False

    def _lane(self, update):
        for kind in (
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
        ):
            if kind in update:
                message = update[kind]
                return ("business", message.get("business_connection_id") or message.get("id"))
        for kind in (
            "message",
            "guest_message",
            "callback_query",
            "inline_query",
            "chosen_inline_result",
        ):
            value = update.get(kind) or {}
            sender = value.get("guest_bot_caller_user") or value.get("from") or {}
            if sender.get("id") is not None:
                return ("user", sender["id"])
        return ("update", update["update_id"])

    def ingest(self, updates):
        for update in updates:
            ident = update.get("update_id")
            if (
                type(ident) is not int
                or ident in self.pending
                or self.offset is not None
                and ident < self.offset
            ):
                continue
            job = PendingUpdate(update, self._lane(update), done=self._stop(update))
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            command = str(message.get("text", "")).split(maxsplit=1)
            administrative = bool(
                command
                and command[0].split("@", 1)[0]
                in {"/start", "/help", "/settings", "/new", "/reset", "/stop", "/clear"}
            )
            if chat.get("type") == "private" and not administrative:
                job.draft = (chat["id"], message.get("message_thread_id") or 0, ident)
                with self.control_lock:
                    self.drafts[job.draft] = job.control
            self.pending[ident] = job
        for job in self.pending.values():
            if job.future and job.future.done():
                self.lanes.pop(job.lane, None)
                if job.future.exception():
                    logging.getLogger(__name__).error(
                        "Telegram dispatch failed for update %s", job.update["update_id"]
                    )
                job.future = None
                job.done = True
        while self.pending:
            first = next(iter(self.pending))
            if not self.pending[first].done:
                break
            self.pending.popitem(last=False)
            self.offset = first + 1
        for ident, job in self.pending.items():
            if len(self.lanes) >= self.workers:
                break
            if job.done or job.future or job.lane in self.lanes:
                continue
            self.lanes[job.lane] = ident
            job.future = self.pool.submit(self._run, job)
            job.future.add_done_callback(lambda _: self.signal.set())

    def _run(self, job):
        try:
            job.control.check()
            self.handle(job.update, job.control)
        except GenerationStopped:
            pass
        finally:
            if job.draft:
                with self.control_lock:
                    self.drafts.pop(job.draft, None)

    def pause(self):
        self.signal.wait(0.25)
        self.signal.clear()

    def close(self):
        with self.control_lock:
            controls = tuple(self.drafts.values())
        for control in controls:
            control.stop()
        self.pool.shutdown(wait=True, cancel_futures=True)
