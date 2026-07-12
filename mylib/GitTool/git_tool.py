from pathlib import Path
import subprocess
import re
from ..LogSet import logSetUp

logger = logSetUp()
def run_git_cmd(params:list[str], cwd:Path|str, )->str|None:
    """
    运行 git 命令
    :param params: 命令参数列表
    :param cwd: 工作目录
    :return: 命令执行结果；发生错误时返回 None
    """
    cmd = ["git"] + params
    process = subprocess.run(
        cmd,  # 要执行的命令列表
        text=True,  # 以文本模式返回输出
        encoding="utf-8",  # 指定编码为 UTF-8
        check=False,  # 不抛出异常，由下方手动判断返回码
        cwd=cwd,  # 指定工作目录
        capture_output=True,  # 捕获标准输出和错误错误输出
    )

    # 非零返回码且存在 stderr 输出时视为真正的错误
    # 注意: git diff 等命令在存在差异时也会返回非零，但不会写 stderr
    if process.returncode != 0 and process.stderr.strip():
        logger.debug(f"git 命令 {' '.join(cmd)} 执行失败: {process.stderr.strip()}")
        return None

    return process.stdout.strip()

def _clear_gitoutput_path(s: str)->Path|None:
    """
    git 输出的路径可能带有引号, 需要去除, 以及去除空文件系统路径
    """

    def _decode_git_octal_path(s: str) -> str:
        """
        将git输出的八进制转回中文路径名称
        """
        bytes_list = []
        i = 0
        while i < len(s):
            if i + 3 < len(s) and s[i] == '\\':
                octal_str = s[i + 1:i + 4]   #每个中文转义数字是3个八进制数字
                if octal_str.isdigit():
                    byte_value = int(octal_str, 8)
                    bytes_list.append(byte_value)
                    i += 4
                    continue

            # 普通字符，直接也转八进制添加
            bytes_list.append(ord(s[i]))
            i += 1

        return bytes(bytes_list).decode('utf-8')

    _s = s.strip(" \"\'")
    if "dev/null" in _s:
        logger.warning(f"发现无效路径: {s}")
        return None

    if Path(_s).exists():
        return Path(_s).resolve()


    decode_path = _decode_git_octal_path(_s)
    if Path(decode_path).exists():
        return Path(decode_path).resolve()

    logger.warning(f"发现无效路径: {s}")
    return None


def compare_folders(dir_old: str | Path, dir_new: str | Path) -> dict:
    """
    使用 git diff 对比两个文件夹的差异
    统一使用 posix 路径(正斜杠)，并开启强力复制与重命名检测
    """
    path_old = Path(dir_old).resolve()
    path_new = Path(dir_new).resolve()

    if not path_old.is_dir() or not path_new.is_dir():
        raise FileNotFoundError("指定的文件夹路径不存在或不是目录。")

    result = {"added": [], "deleted": [], "modified": [], "renamed": [], "copied": []}
    params = [
        "diff",
        "--no-index",           # 不使用仓库索引，直接对比文件内容
        "--name-status",        # 仅显示文件名和状态，不显示差异内容
        "-M",                   # 文件重命名检测
        "--find-copies-harder", # 开启强力复制与重命名检测
        path_old.as_posix(),
        path_new.as_posix(),
    ]

    output = run_git_cmd(params, cwd=Path.cwd())
    if output is None:
        logger.debug("错误: git diff 执行失败。")
        return result

    lines = output.splitlines()
    for line in lines:
        if not line.strip():
            continue

        parts = line.split("\t")
        parts = [p.strip(" \"\'") for p in parts]
        status = parts[0]

        # Git 返回的路径也会是正斜杠，Path 会自动兼容解析
        if status.startswith("A"):
            tmp_path = _clear_gitoutput_path(parts[1])
            if tmp_path:
                result["added"].append(tmp_path.relative_to(path_new))
        elif status.startswith("D"):
            tmp_path = _clear_gitoutput_path(parts[1])
            if tmp_path:
                result["deleted"].append(tmp_path.relative_to(path_old))
        elif status.startswith("M"):
            tmp_path = _clear_gitoutput_path(parts[1])
            if tmp_path:
                result["modified"].append(tmp_path.relative_to(path_new))
        elif status.startswith("R"):
            tmp_path_old = _clear_gitoutput_path(parts[1])
            tmp_path_new = _clear_gitoutput_path(parts[2])
            if tmp_path_old and tmp_path_new:
                result["renamed"].append(
                {
                    "old": tmp_path_old.relative_to(path_old),
                    "new": tmp_path_new.relative_to(path_new),
                }
            )
        elif status.startswith("C"):
            tmp_path_old = _clear_gitoutput_path(parts[1])
            tmp_path_new = _clear_gitoutput_path(parts[2])
            if tmp_path_old and tmp_path_new:
                result["copied"].append(
                {
                    "from": tmp_path_old.relative_to(path_old),
                    "to": tmp_path_new.relative_to(path_new),
                }
            )
        else:
            logger.warning(f"未知未知状态: {status}")
    return result


def get_diff_line_count(
    dir_old: str,
    dir_new: str,
    filter_suffix:set[str]|tuple[str] = None,
)-> int:
    tmp_dict = get_diff_line_stats(dir_old, dir_new)
    if not filter_suffix:
        return tmp_dict["total_insertions"] + tmp_dict["total_deletions"]

    res = 0
    for file_path_str, info in tmp_dict["files"].items():
        if file_path_str.lower().endswith(tuple(filter_suffix)):
           res += info["total"]
    return res

def get_diff_line_stats(root_old: str | Path, root_new: str | Path) -> dict:
    """
    获取两个文件夹中每个文件的变更行数。
    完全复制/重命名且未修改的文件，变更行数为 0。

    返回结构:
    {
        'files': { 'file_path': {'insertions': 10, 'deletions': 5, 'total': 15}, ... },
        'total_insertions': 100,
        'total_deletions': 50
    }
    """

    def _parse_git_rename_path(raw_path: str, path_old: Path, path_new: Path) -> Path:
        """
        把 Git 重命名/复制 的条目中的路径（如 'dir/{old => new}/a.txt'）转换为新目录的相对路径
        将其它情况的路径转换为各自目录的相对路径
        支持中文路径
        """
        # 如果包含 => 说明触发了重命名或复制
        if "=>" in raw_path:
            # 正则提取 => 后面的路径部分
            # 比如： "src/{old_dir => new_dir}/file.js" -> "src/new_dir/file.js"
            match = re.search(r"(.*)\{(.*)\s=>\s(.*)\}(.*)", raw_path)
            if match:
                prefix, _, to_path, suffix = match.groups()
                to_path = to_path.strip(" \"\'")  # 移除可能的引号
                final_str = f"{prefix}{to_path}{suffix}".replace("//", "/").strip()
            else:
                # 若形式为 "old.txt => new.txt"
                final_str = raw_path.split("=>")[1].strip()
                final_str = final_str.strip(" \"\'")  # 移除可能的引号

            # 最终映射为相对新目录的路径
            # full_path = Path(final_str)
            # if full_path.is_absolute():
            #     return full_path.relative_to(path_new)
            # return full_path
        else:
            # 普通的增加、删除、修改路径
            final_str = raw_path.strip(" \"\'")

        final_str = str(_clear_gitoutput_path(final_str))

        p = Path(final_str.strip(" \"\'"))
        if p.is_relative_to(path_new):
            return p.relative_to(path_new)
        elif p.is_relative_to(path_old):
            return p.relative_to(path_old)
        return p

    root_old = Path(root_old).resolve()
    root_new = Path(root_new).resolve()

    if not root_old.is_dir() or not root_new.is_dir():
        raise FileNotFoundError("指定的文件夹路径不存在。")

    # 使用 --numstat 可以输出清晰的数字：增加行数  删除行数  文件名
    params = [
        "diff",
        "--no-index",
        "--numstat",
        "-M",
        "--find-copies-harder",
        root_old.as_posix(),
        root_new.as_posix(),
    ]

    output = run_git_cmd(params, cwd=Path.cwd())
    stats = {"files": {}, "total_insertions": 0, "total_deletions": 0}

    if not output:
        return stats

    lines = output.split("\n")

    for line in lines:
        if not line.strip():
            continue

        # --numstat 的输出格式为: 增加行数\t删除行数\t文件名
        # 如果是重命名/复制，文件名部分会变成: old_path => new_path 或 {old => new}/file.txt
        parts = line.split("\t")
        if len(parts) < 3:
            continue

        insertions_str, deletions_str, file_path_raw = parts[0], parts[1], parts[2]

        # 处理二进制文件的情况 (二进制文件在 numstat 中显示为 '-')
        if insertions_str == "-" or deletions_str == "-":
            insertions = 0
            deletions = 0
        else:
            insertions = int(insertions_str)
            deletions = int(deletions_str)

        # 解析复杂的重命名/复制路径，提取出它在“新文件夹”中的相对路径名
        clean_path:Path = _parse_git_rename_path(file_path_raw, root_old, root_new)
        stats["files"][str(clean_path)] = {
            "insertions": insertions,
            "deletions": deletions,
            "total": insertions + deletions,
        }

        stats["total_insertions"] += insertions
        stats["total_deletions"] += deletions

    return stats


def test():
    folder_old = r"C:/Users/ace/Documents/Code/Test/sub_repo"
    folder_new = r"C:/Users/ace/Documents/Code/Test/main_repo"

    try:
        line_stats = get_diff_line_stats(folder_old, folder_new)
        print("📊 每个文件的变更行数明细：")
        for f_path, info in line_stats["files"].items():
            print(f"📄 文件: {f_path}")
            print(
                f"   增加: {info['insertions']} 行, 删除: {info['deletions']} 行, 总变更: {info['total']} 行"
            )

        print(f"🔥 总增加行数: {line_stats['total_insertions']}")
        print(f"💧 总删除行数: {line_stats['total_deletions']}")

        print(compare_folders(folder_old, folder_new))
    except Exception as e:
        print(f"运行失败: {e}")
