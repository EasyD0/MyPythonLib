import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..LogSet import log_set

logger = log_set(__name__)


@dataclass
class FileInfo:
    name: str
    time: str
    location: Path
    is_dir: bool = False  # True 表示该条目实际是目录(被忽略内部的隐藏目录, 或符号链接指向的目录)


class FileTree:

    def __init__(self, dir: Path, ignore_hidden: bool = True):
        self.curFiles: list[FileInfo] = []
        self.curDirs: list["FileTree"] = []
        self.dir_path: Path = dir.resolve()
        self.ignore_hidden: bool = ignore_hidden

        # 构建文件树
        self._build_tree(dir)

    def _make_file_info(self, entry: os.DirEntry, is_dir: bool = False) -> FileInfo:
        """从 scandir 条目构造 FileInfo, mtime 直接取 scandir 缓存的 stat 结果"""
        mtime = datetime.fromtimestamp(entry.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return FileInfo(
            name=entry.name, time=mtime, location=Path(entry.path), is_dir=is_dir
        )

    def _build_tree(self, dir: Path):
        """递归构建文件树"""
        try:
            with os.scandir(dir) as it:
                # 目录排前, 文件排后; is_dir/is_symlink/stat 由 scandir 缓存, 每项只触发一次系统调用
                entries = sorted(it, key=lambda e: (not e.is_dir(), e.name))

            for entry in entries:
                is_dir = entry.is_dir()

                # 符号链接/junction(Windows reparse point)只显示自身, 不递归进入,
                # 规避循环链接导致的死循环; is_symlink 不识别 junction, 需检查 reparse 标记
                st = entry.stat(follow_symlinks=False)
                is_reparse = stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) != 0
                if is_reparse:
                    self.curFiles.append(self._make_file_info(entry, is_dir=is_dir))
                    continue

                if is_dir:
                    if self.ignore_hidden and entry.name.startswith("."):
                        # 忽略目录内部, 但添加目录本身
                        self.curFiles.append(self._make_file_info(entry, is_dir=True))
                    else:
                        # 创建子目录的 FileTree
                        child_tree = FileTree(Path(entry.path), self.ignore_hidden)
                        self.curDirs.append(child_tree)
                else:
                    # 添加文件信息
                    self.curFiles.append(self._make_file_info(entry))
        except Exception as e:
            logger.error(f"构建文件树时出错 {dir}: {e}")

    def _str(self, ignore_dir_name: set[str] | None = None):
        """将文件树转换为字符串表示"""
        lines = []
        ignore_dir_name = ignore_dir_name or set()

        def format_tree(tree: "FileTree", prefix: str = "", is_last: bool = True):
            """递归格式化文件树"""
            # 处理目录本身

            # 添加目录下的文件(含被忽略内部的目录, 目录条目带 / 后缀)
            for i, file in enumerate(tree.curFiles):
                is_file_last = i == len(tree.curFiles) - 1
                file_prefix = "└── " if (is_file_last and not tree.curDirs) else "├── "
                suffix = "/" if file.is_dir else ""
                lines.append(f"{prefix}{file_prefix}{file.name}{suffix} ({file.time})")

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

    def print_tree(self, ignore_dir_name: set[str] | None = None):
        """打印文件树"""
        print(f"{self.dir_path.resolve()}下的文件为:")
        print(self._str(ignore_dir_name))


def print_file_tree(
        root_dir: Path,
        ignore_dir_name: set[str] | None = None,
        ignore_hidden: bool = True,
):
    """
    打印目录的文件树, 如果某个子文件夹在 ignore_dir_name 中, 则不显示其内部的文件, 但显示这个文件夹
    文件名需要带有修改时间
    """
    if ignore_dir_name is None:
        ignore_dir_name = {"tmp_repo", ".git"}
    file_tree = FileTree(root_dir, ignore_hidden)
    file_tree.print_tree(ignore_dir_name=ignore_dir_name)
