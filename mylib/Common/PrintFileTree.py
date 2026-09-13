import os
from dataclasses import dataclass
from pathlib import Path

import datetime

from ..LogSet import log_set

logger = log_set(__name__)


@dataclass
class FileInfo:
    name: str
    time: str
    location: Path


class FileTree:

    def __init__(self, dir: Path, ignore_hidden: bool = True):
        self.curFiles: list[FileInfo] = []
        self.curDirs: list["FileTree"] = []
        self.dir_path: Path = dir.resolve()
        self.ignore_hidden: bool = ignore_hidden

        # 构建文件树
        self._build_tree(dir)

    def _build_tree(self, dir: Path):
        """递归构建文件树"""
        try:
            items = sorted(dir.iterdir(), key=lambda x: (not x.is_dir(), x.name))

            for item in items:
                # 检查是否为隐藏文件夹（以.开头）
                is_hidden = item.name.startswith(".")

                if item.is_dir():
                    if self.ignore_hidden and is_hidden:
                        # 忽略目录内部，但添加目录本身
                        file_info = FileInfo(
                            name=item.name,
                            time=datetime.fromtimestamp(
                                os.path.getmtime(item)
                            ).strftime("%Y-%m-%d %H:%M:%S"),
                            location=item,
                        )
                        self.curFiles.append(file_info)
                    else:
                        # 创建子目录的 FileTree
                        child_tree = FileTree(item, self.ignore_hidden)
                        self.curDirs.append(child_tree)
                else:
                    # 添加文件信息
                    file_info = FileInfo(
                        name=item.name,
                        time=datetime.fromtimestamp(os.path.getmtime(item)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        location=item,
                    )
                    self.curFiles.append(file_info)
        except Exception as e:
            logger.error(f"构建文件树时出错 {dir}: {e}")

    def _str(self, ignore_dir_name: set[str] = None):
        """将文件树转换为字符串表示"""
        lines = []
        ignore_dir_name = ignore_dir_name or set()

        def format_tree(tree: "FileTree", prefix: str = "", is_last: bool = True):
            """递归格式化文件树"""
            # 处理目录本身

            # 添加目录下的文件
            for i, file in enumerate(tree.curFiles):
                is_file_last = i == len(tree.curFiles) - 1
                file_prefix = "└── " if (is_file_last and not tree.curDirs) else "├── "
                lines.append(f"{prefix}{file_prefix}{file.name} ({file.time})")

            # 递归处理子目录
            for i, child in enumerate(tree.curDirs):
                is_child_last = i == len(tree.curDirs) - 1
                child_prefix = "└── " if is_child_last else "├── "
                lines.append(f"{prefix}{child_prefix}{child.dir_path.name}/")

                # 递归打印子目录内容
                if child.dir_path.name not in ignore_dir_name:
                    new_prefix = prefix + ("    " if is_child_last else "│   ")
                    format_tree(child, new_prefix, True)

        # 添加根目录名
        lines.append(f"{self.dir_path.name}/")
        format_tree(self, "", True)

        return "\n".join(lines)

    def __str__(self):
        return self._str()

    def print(self, ignore_dir_name: set[str] = None):
        """打印文件树"""
        print(f"{self.dir_path.resolve()}下的文件为:")
        print(self._str(ignore_dir_name))


def print_file_tree(
        root_dir: Path,
        ignore_dir_name: set[str] = None,
        ignore_hidden: bool = True,
):
    """
    打印目录的文件树, 如果某个子文件夹在 ignore_dir_name 中, 则不显示其内部的文件, 但显示这个文件夹
    文件名需要带有修改时间
    """
    if ignore_dir_name is None:
        ignore_dir_name = {"tmp_repo", ".git"}
    file_tree = FileTree(root_dir, ignore_hidden)
    file_tree.print(ignore_dir_name=ignore_dir_name)
