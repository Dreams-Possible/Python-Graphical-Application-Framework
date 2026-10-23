"""应用级后台任务运行器：独立输入、协作取消与异步退出。"""

from dataclasses import dataclass
import logging
from threading import Event
from time import monotonic
from typing import Callable, Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

LOGGER = logging.getLogger("workbench.tasks")


class TaskCancelled(Exception):
    pass


def check_cancelled(cancelled: Event) -> None:
    if cancelled.is_set():
        raise TaskCancelled()


class _Worker(QObject):
    outcome = Signal(str, int, object, str, bool)
    finished = Signal()

    def __init__(self, key: str, generation: int, function: Callable[[Event], Any], cancelled: Event) -> None:
        super().__init__()
        self.key, self.generation = key, generation
        self.function, self.cancelled = function, cancelled

    @Slot()
    def run(self) -> None:
        started = monotonic()
        state = "失败"
        try:
            check_cancelled(self.cancelled)
            result = self.function(self.cancelled)
            check_cancelled(self.cancelled)
            self.outcome.emit(self.key, self.generation, result, "", False)
            state = "成功"
        except TaskCancelled:
            state = "取消"
            self.outcome.emit(self.key, self.generation, None, "已取消", True)
        except Exception as error:
            LOGGER.exception("后台任务失败：%s", self.key)
            self.outcome.emit(self.key, self.generation, None, str(error), False)
        finally:
            LOGGER.info("任务结果：%s，代次 %d，%s，耗时 %.2f 秒", self.key, self.generation, state, monotonic() - started)
            self.finished.emit()


@dataclass
class _Job:
    key: str
    generation: int
    thread: QThread
    worker: _Worker
    cancelled: Event


class TaskRunner(QObject):
    completed = Signal(str, int, object, str, bool)
    drained = Signal()
    activity_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._jobs: dict[QThread, _Job] = {}
        self._sequence = 0
        self._closing = False

    def submit(self, key: str, function: Callable[[Event], Any]) -> int:
        if self._closing:
            raise RuntimeError("应用正在退出")
        if any(job.key == key for job in self._jobs.values()):
            raise RuntimeError("该任务仍在结束，请稍后重试")
        self._sequence += 1
        generation = self._sequence
        thread = QThread(self)
        thread.setObjectName(key)
        cancelled = Event()
        worker = _Worker(key, self._sequence, function, cancelled)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.outcome.connect(self._deliver)
        worker.finished.connect(worker.deleteLater)
        # quit 线程安全，直接连接使关闭不依赖 GUI 阻塞等待。
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(self._reap)
        self._jobs[thread] = _Job(key, self._sequence, thread, worker, cancelled)
        thread.start()
        self.activity_changed.emit(len(self._jobs))
        LOGGER.info("后台任务开始：%s，代次 %d", key, generation)
        return generation

    @Slot(str, int, object, str, bool)
    def _deliver(self, key: str, generation: int, result: object, error: str, cancelled: bool) -> None:
        if not self._closing:
            self.completed.emit(key, generation, result, error, cancelled)

    @Slot()
    def _reap(self) -> None:
        thread = self.sender()
        job = self._jobs.pop(thread, None)
        if job is not None:
            LOGGER.info("后台任务结束：%s", job.key)
            thread.deleteLater()
        self.activity_changed.emit(len(self._jobs))
        if not self._jobs:
            self.drained.emit()

    def cancel(self, key: str) -> None:
        for job in self._jobs.values():
            if job.key == key:
                LOGGER.info("请求取消后台任务：%s，代次 %d", key, job.generation)
                job.cancelled.set()

    def is_active(self, key: str) -> bool:
        return any(job.key == key for job in self._jobs.values())

    def shutdown(self) -> bool:
        LOGGER.info("任务系统开始关闭，等待 %d 个任务结束", len(self._jobs))
        self._closing = True
        for job in self._jobs.values():
            job.cancelled.set()
        return not self._jobs

    @property
    def active_count(self) -> int:
        return len(self._jobs)
