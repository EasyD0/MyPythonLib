# mypylib

个人 Python 工具库，包含 Git 工具、日志设置和线程池实现。

## 功能模块

### LogSet
日志设置模块，提供自定义格式化的日志配置。

```python
from mypylib.LogSet import logSetUp

logger = logSetUp("MyLogger")
logger.info("这是一条日志")
```

### GitTool
Git 工具模块，提供文件夹对比和变更统计功能。

```python
from mypylib.GitTool.git_tool import compare_folders, get_diff_line_stats

diff = compare_folders("old_dir", "new_dir")
stats = get_diff_line_stats("old_dir", "new_dir")
```

### ThreadPool
线程池模块，基于 Future 的异步任务执行。

```python
from mypylib.ThreadPool.threadpool import ThreadPool

pool = ThreadPool(4)
future = pool.submit(my_function, arg1, arg2)
result = future.result()
```

## 安装

```bash
# 开发模式安装
pip install -e .

# 正式安装
pip install .
```

## 要求

- Python >= 3.13

## 许可证

MIT License