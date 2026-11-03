"""Background work without freezing the GUI.

``run_task(fn, ...)`` executes ``fn(task)`` in the global QThreadPool.  The
function receives a ``Task`` it can use to report progress, stream tokens and
check for cancellation; results and errors are delivered back on the GUI
thread through Qt signals.
"""
from __future__ import annotations

import logging
import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)
_active: set["Task"] = set()


class TaskSignals(QObject):
    progress = Signal(int, int, str)
    token = Signal(str)
    result = Signal(object)
    error = Signal(object)  # the exception
    finished = Signal()


class Task(QRunnable):
    def __init__(self, fn: Callable[["Task"], Any]):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()
        self.cancel_event = threading.Event()
        self.setAutoDelete(False)

    # helpers available to the worker function
    def progress(self, done: int, total: int, msg: str = "") -> None:
        self.signals.progress.emit(int(done), int(total), msg)

    def token(self, text: str) -> None:
        self.signals.token.emit(text)

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            out = self.fn(self)
        except BaseException as exc:  # noqa: BLE001
            log.warning("Background task failed: %s", type(exc).__name__)
            log.debug("".join(traceback.format_exception(exc)))
            try:
                self.signals.error.emit(exc)
            except RuntimeError:
                pass
        else:
            try:
                self.signals.result.emit(out)
            except RuntimeError:
                pass
        finally:
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass
            _active.discard(self)


def run_task(fn: Callable[[Task], Any], on_result: Callable | None = None, on_error: Callable | None = None,
             on_progress: Callable | None = None, on_token: Callable | None = None,
             on_finished: Callable | None = None) -> Task:
    t = Task(fn)
    if on_result:
        t.signals.result.connect(on_result)
    if on_error:
        t.signals.error.connect(on_error)
    if on_progress:
        t.signals.progress.connect(on_progress)
    if on_token:
        t.signals.token.connect(on_token)
    if on_finished:
        t.signals.finished.connect(on_finished)
    _active.add(t)
    QThreadPool.globalInstance().start(t)
    return t


def cancel_all() -> None:
    for t in list(_active):
        t.cancel()


def wait_all(ms: int = 5000) -> bool:
    return QThreadPool.globalInstance().waitForDone(ms)
