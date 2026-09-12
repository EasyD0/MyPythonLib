import queue
from concurrent.futures import Future
from threading import Thread, Lock, Event, Condition
from ..LogSet import log_set
from enum import Enum
from typing import Callable

logger = log_set("")


class PoolStatus(Enum):
    RUNNING = 0
    STOPPING = 1
    STOPPED = 2


class task_wrapper:
    def __init__(self, func: Callable, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.future = Future()

    def get_future(self) -> Future:
        return self.future

    def execute(self) -> None:
        try:
            self.future.set_result(self.func(*self.args, **self.kwargs))
        except Exception as e:
            self.future.set_exception(e)


class Worker(Thread):
    """
    消费者
    """

    id: int = 0

    def __init__(self, task_queue: queue.Queue):
        super().__init__(daemon=True)
        self._id = Worker.id
        Worker.id += 1
        self.task_queue = task_queue
        self._stop_event = Event()

    def run(self):
        """实际的任务函数"""
        while not self._stop_event.is_set():
            task = self.task_queue.get()
            if task is None:
                break

            future = task.get_future()

            if not future.set_running_or_notify_cancel():
                self.task_queue.task_done()
                continue

            try:
                task.execute()
            finally:
                self.task_queue.task_done()

    def stop(self):
        self._stop_event.set()


class ThreadPool:
    def __init__(self, pool_size: int):
        self.task_queue: queue.Queue = queue.Queue()
        self.pool_size = pool_size

        self.workers: list[Worker] = []
        self.status: PoolStatus = PoolStatus.STOPPED
        self.start()

    def start(self):
        if self.status == PoolStatus.RUNNING:
            logger.info("当前线程池已启动")
            return
        if self.status == PoolStatus.STOPPING:
            logger.info("当前线程池正在停止")
            return

        for _ in range(self.pool_size):
            self._create_one_worker()

        self.status = PoolStatus.RUNNING

    def _create_one_worker(self):
        worker_handler = Worker(self.task_queue)
        self.workers.append(worker_handler)
        worker_handler.start()

    def submit(self, fn, *args, **kwargs):
        """生产者：向池中提交任务，立即返回 Future"""
        if self.status != PoolStatus.RUNNING:
            raise RuntimeError("不在运行中, 无法提交任务")

        task = task_wrapper(fn, *args, **kwargs)
        self.task_queue.put(task)
        return task.get_future()

    def stop(self):
        """优雅关闭"""
        if self.status != PoolStatus.RUNNING:
            logger.info("当前线程池不在运行中, 无法停止")
            return

        self.status = PoolStatus.STOPPING

        for w in self.workers:
            w.stop()
        for _ in range(len(self.workers)):
            self.task_queue.put(None)
        for w in self.workers:
            w.join()

        self.workers = []
        self.status = PoolStatus.STOPPED

    def resize(self, new_size: int):
        if new_size == self.pool_size:
            return
        if self.status != PoolStatus.RUNNING:
            self.pool_size = new_size
            return

        if new_size > self.pool_size:
            for _ in range(new_size - self.pool_size):
                self._create_one_worker()
            self.pool_size = new_size
            return

        if new_size < self.pool_size:
            to_remove = self.pool_size - new_size
            victims = self.workers[-to_remove:]
            for w in victims:
                w.stop()
                self.task_queue.put(None)
            for w in victims:
                w.join()
            self.workers = self.workers[:-to_remove]
            self.pool_size = new_size