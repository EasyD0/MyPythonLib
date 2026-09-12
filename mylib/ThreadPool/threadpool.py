from queue import Queue
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
        self.future.set_result(self.func(*self.args, **self.kwargs))


class Worker:
    """
    消费者
    """

    id: int = 0

    def __init__(self, task_queue: Queue[task_wrapper], condition: Condition):
        self._id = Worker.id
        Worker.id += 1
        self.task_queue = task_queue
        self._stop_event = Event()
        self.condition = condition

    def _job(self):
        """实际的任务函数"""
        while not self._stop_event.is_set():
            with self.condition:
                # 获取一个任务封装（Future, 函数, 参数）
                task = self.task_queue.get()
                if task is None:  # 收到停止信号
                    continue

                future = task.get_future()

                # 检查 Future 是否已被取消
                if not future.set_running_or_notify_cancel():
                    self.task_queue.task_done()
                    continue

                try:
                    # 执行任务并设置结果
                    task.execute()
                except Exception as e:
                    # 捕获异常并传递给 Future
                    future.set_exception(e)
                finally:
                    self.task_queue.task_done()

    def stop(self):
        self._stop_event.set()

    def restart(self):
        self._stop_event.clear()


class ThreadPool:
    def __init__(self, pool_size):
        self.task_queue = queue.Queue()
        self.pool_size = pool_size

        self.workers: list[Worker] = []
        self.status: PoolStatus = PoolStatus.STOPPED
        self.notify_condition = Condition()
        self.start()

    def start(self):
        if self.status == PoolStatus.RUNNING:
            logger.info("当前线程池已启动")
            return
        if self.status == PoolStatus.STOPPING:
            logger.info("当前线程池正在停止")
            return

        self.workers = []

        # 初始化并启动消费者线程 (Workers)
        for _ in range(self.pool_size):
            self._create_one_worker()

        self.status = PoolStatus.RUNNING

    def _create_one_worker(self):
        worker_handler = Worker(self.task_queue, self.notify_condition)
        self.workers.append(worker_handler)
        worker_handler.start()

    def _worker(self):
        """消费者：不断从队列中提取任务并执行"""
        while True:
            # 获取一个任务封装（Future, 函数, 参数）
            task_item = self.task_queue.get()
            if task_item is None:  # 收到停止信号
                break

            future, fn, args, kwargs = task_item

            # 检查 Future 是否已被取消
            if not future.set_running_or_notify_cancel():
                self.task_queue.task_done()
                continue

            try:
                # 执行任务并设置结果
                result = fn(*args, **kwargs)
                future.set_result(result)
            except Exception as e:
                # 捕获异常并传递给 Future
                future.set_exception(e)
            finally:
                self.task_queue.task_done()

    def submit(self, fn, *args, **kwargs):
        """生产者：向池中提交任务，立即返回 Future"""
        if self.status != PoolStatus.RUNNING:
            raise RuntimeError("不在运行中, 无法提交任务")

        # 创建 Future 对象
        task = task_wrapper(fn, *args, **kwargs)

        # 将任务包装后放入队列
        self.task_queue.put(task)
        return task.get_future()

    def stop(self):
        """优雅关闭"""
        if self.status != PoolStatus.RUNNING:
            logger.info("当前线程池不在运行中, 无法停止")
            return

        self.status = PoolStatus.STOPPING
        for _ in range(len(self.workers)):
            self.task_queue.put(None)
        for t in self.workers:
            t.join()

        self.workers = []
        self.status = PoolStatus.STOPPED

    def resize(self, new_size: int):
        if new_size == self.pool_size:
            return
        if self.status != PoolStatus.RUNNING:
            self.pool_size = new_size
            return

        if new_size > self.pool_size:
            for i in range(new_size - self.pool_size):
                self._create_one_worker()
            self.pool_size = new_size
            return

        if new_size < self.pool_size:
            for i in range(self.pool_size - new_size):
                pass
