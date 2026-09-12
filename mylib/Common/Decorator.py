import asyncio
import inspect
import threading
import time
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

        is_async = inspect.iscoroutinefunction(func)

        if is_async:

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


def test():
    lock = threading.Lock()
