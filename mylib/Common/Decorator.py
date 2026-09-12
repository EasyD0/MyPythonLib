import asyncio
import inspect
import threading
import time
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Callable


def elapse(f: Callable) -> Callable:
    """
    检查函数执行耗时
    """

    @wraps(f)
    def new_f(*args, **kwargs):
        t_start = time.time()
        result = f(*args, **kwargs)
        t_end = time.time()
        print(f"{f.__name__} 执行耗时: {t_end - t_start:.4f} s")
        return result

    return new_f


def noexcept(f: Callable) -> Callable:
    """
    捕获函数执行异常, 异常时打印并返回 None, 支持同步与 async 函数
    """

    if inspect.iscoroutinefunction(f):

        @wraps(f)
        async def new_f(*args, **kwargs):
            try:
                return await f(*args, **kwargs)
            except Exception as e:
                print(f"{f.__name__} 执行异常: {e}")
                return None

    else:

        @wraps(f)
        def new_f(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                print(f"{f.__name__} 执行异常: {e}")
                return None

    return new_f


def url_set(_url: str):
    """
    检查函数是否存在 名为 `url`的参数, 如果有, 则为这个形参设置默认实参为 `_url` 的值
    可以装饰 asyncio 函数
    """

    def decorator(func):
        sig = inspect.signature(func)
        if "url" not in sig.parameters:
            return func

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def new_f(*args, **kwargs):
                bound = sig.bind_partial(*args, **kwargs)
                if "url" not in bound.arguments:
                    kwargs.setdefault("url", _url)
                return await func(*args, **kwargs)

        else:

            @wraps(func)
            def new_f(*args, **kwargs):
                bound = sig.bind_partial(*args, **kwargs)
                if "url" not in bound.arguments:
                    kwargs.setdefault("url", _url)
                return func(*args, **kwargs)

        return new_f

    return decorator


def retry(
    times: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> Callable:
    """
    失败自动重试装饰器, 支持同步与 async 函数
    所有重试均失败后, 最后一次的异常会向上抛出

    :param times: 最大尝试次数(含首次调用), 小于 1 时按 1 处理
    :param delay: 首次重试前的等待时间(秒)
    :param backoff: 退避倍数, 第 n 次重试的等待时间为 delay * backoff ** (n - 1)
    :param exceptions: 触发重试的异常类型(单个类型或元组), 其余异常直接向上抛出, 不重试
    """

    def decorator(func: Callable) -> Callable:
        max_attempts = max(int(times), 1)
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def new_f(*args, **kwargs):
                wait = delay
                for attempt in range(1, max_attempts + 1):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        if attempt >= max_attempts:
                            raise
                        print(f"{func.__name__} 第 {attempt} 次执行失败: {e}, {wait:.2f} s 后重试")
                        await asyncio.sleep(wait)
                        wait *= backoff

        else:

            @wraps(func)
            def new_f(*args, **kwargs):
                wait = delay
                for attempt in range(1, max_attempts + 1):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        if attempt >= max_attempts:
                            raise
                        print(f"{func.__name__} 第 {attempt} 次执行失败: {e}, {wait:.2f} s 后重试")
                        time.sleep(wait)
                        wait *= backoff

        return new_f

    return decorator


# 供 timeout 装饰器使用的共享执行器, 避免每次调用都创建线程
_timeout_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="timeout-watchdog")


def timeout(seconds: float) -> Callable:
    """
    函数执行超时控制装饰器, 超时后抛出 TimeoutError, 支持同步与 async 函数
    注意: 同步函数超时后, 原函数仍会在后台线程中继续执行至结束(线程无法强制终止),
    只是调用方提前收到 TimeoutError

    :param seconds: 超时时间(秒)
    """

    def decorator(func: Callable) -> Callable:
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def new_f(*args, **kwargs):
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)

        else:

            @wraps(func)
            def new_f(*args, **kwargs):
                future = _timeout_executor.submit(func, *args, **kwargs)
                return future.result(timeout=seconds)

        return new_f

    return decorator


def singleton(cls: Callable) -> Callable:
    """
    单例装饰器(线程安全): 被装饰的类无论实例化多少次, 都返回同一个实例

    :param cls: 被装饰的类
    """
    instances: dict = {}
    lock = threading.Lock()

    @wraps(cls, updated=[])
    def get_instance(*args, **kwargs):
        if cls not in instances:
            with lock:
                if cls not in instances:
                    instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


def cache(ttl: float = 60.0, maxsize: int = 128) -> Callable:
    """
    带过期时间的缓存装饰器(线程安全), 支持同步与 async 函数
    仅支持参数可哈希的函数; 不同参数组合分别缓存

    :param ttl: 缓存有效期(秒), 超过该时间后重新计算结果
    :param maxsize: 最大缓存条目数, 超出后淘汰最早写入的条目
    """

    def decorator(func: Callable) -> Callable:
        store: OrderedDict = OrderedDict()
        lock = threading.Lock()
        is_async = inspect.iscoroutinefunction(func)

        def _make_key(args, kwargs):
            return (args, tuple(sorted(kwargs.items())))

        def _hit(key) -> bool:
            """检查缓存是否命中, 命中时返回 True 并刷新访问顺序"""
            hit = store.get(key)
            if hit is not None and time.monotonic() - hit[0] < ttl:
                store.move_to_end(key)
                return True
            return False

        if is_async:

            @wraps(func)
            async def new_f(*args, **kwargs):
                key = _make_key(args, kwargs)
                with lock:
                    if _hit(key):
                        return store[key][1]

                result = await func(*args, **kwargs)
                with lock:
                    store[key] = (time.monotonic(), result)
                    store.move_to_end(key)
                    while len(store) > maxsize:
                        store.popitem(last=False)
                return result

        else:

            @wraps(func)
            def new_f(*args, **kwargs):
                key = _make_key(args, kwargs)
                with lock:
                    if _hit(key):
                        return store[key][1]

                result = func(*args, **kwargs)
                with lock:
                    store[key] = (time.monotonic(), result)
                    store.move_to_end(key)
                    while len(store) > maxsize:
                        store.popitem(last=False)
                return result

        return new_f

    return decorator


def rate_limit(times: int, per_seconds: float, block: bool = True) -> Callable:
    """
    限流装饰器, 基于滑动时间窗口限制调用频率, 支持同步与 async 函数

    :param times: 时间窗口内允许的最大调用次数
    :param per_seconds: 时间窗口长度(秒)
    :param block: 超出限流时的行为; True 表示阻塞等待至窗口有空位后继续执行,
                  False 表示直接抛出 RuntimeError
    """

    def decorator(func: Callable) -> Callable:
        call_times: deque[float] = deque()
        lock = threading.Lock()
        is_async = inspect.iscoroutinefunction(func)

        def _try_acquire() -> float | None:
            """尝试获取一个调用名额; 成功返回 None, 否则返回建议等待时长(秒)"""
            with lock:
                now = time.monotonic()
                while call_times and now - call_times[0] > per_seconds:
                    call_times.popleft()
                if len(call_times) < times:
                    call_times.append(now)
                    return None
                return per_seconds - (now - call_times[0])

        def _reject(wait_time: float):
            if not block:
                raise RuntimeError(
                    f"{func.__name__} 调用过于频繁: {per_seconds} 秒内最多 {times} 次"
                )
            return wait_time

        if is_async:

            @wraps(func)
            async def new_f(*args, **kwargs):
                while (wait_time := _try_acquire()) is not None:
                    await asyncio.sleep(_reject(wait_time))
                return await func(*args, **kwargs)

        else:

            @wraps(func)
            def new_f(*args, **kwargs):
                while (wait_time := _try_acquire()) is not None:
                    time.sleep(_reject(wait_time))
                return func(*args, **kwargs)

        return new_f

    return decorator


def test():
    lock = threading.Lock()
