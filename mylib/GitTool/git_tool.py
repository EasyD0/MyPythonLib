from pathlib import Path
import subprocess
import re

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
        capture_output=True
    )

    # 非零返回码且存在 stderr 输出时视为真正的错误
    # 注意: git diff 等命令在存在差异时也会返回非零，但不会写 stderr
    if process.returncode != 0 and process.stderr.strip():
        print(f"git 命令 {' '.join(cmd)} 执行失败: {process.stderr.strip()}")
        return None

    return process.stdout.strip()

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

    # 使用 .as_posix() 统一将 Windows 的 \\ 转换为 /
    # 同时保留 -M 和 --find-copies-harder
    params = [
        "diff",
        "--no-index",
        "--name-status",
        "-M",
        "--find-copies-harder",
        path_old.as_posix(),
        path_new.as_posix(),
    ]

    output = run_git_cmd(params, cwd=Path.cwd())
    if output is None:
        print("错误: git diff 执行失败。")
        return result

    lines = output.split("\n")

    for line in lines:
        if not line.strip():
            continue

        parts = line.split("\t")
        parts = [p.strip(" \"\'") for p in parts]
        status = parts[0]

        # Git 返回的路径也会是正斜杠，Path 会自动兼容解析
        if status.startswith("A"):
            result["added"].append(Path(parts[1]).relative_to(path_new))
        elif status.startswith("D"):
            result["deleted"].append(Path(parts[1]).relative_to(path_old))
        elif status.startswith("M"):
            result["modified"].append(Path(parts[1]).relative_to(path_new))
        elif status.startswith("R"):
            result["renamed"].append(
                {
                    "old": Path(parts[1]).relative_to(path_old),
                    "new": Path(parts[2]).relative_to(path_new),
                }
            )
        elif status.startswith("C"):
            result["copied"].append(
                {
                    "from": Path(parts[1]).relative_to(path_old),
                    "to": Path(parts[2]).relative_to(path_new),
                }
            )
        else:
            print(f"警告: 未知未知状态: {status}")




    return result

def get_diff_line_stats(dir_old: str | Path, dir_new: str | Path) -> dict:
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
    path_old = Path(dir_old).resolve()
    path_new = Path(dir_new).resolve()

    if not path_old.is_dir() or not path_new.is_dir():
        raise FileNotFoundError("指定的文件夹路径不存在。")

    # 使用 --numstat 可以输出清晰的数字：增加行数  删除行数  文件名
    params = [
        "diff",
        "--no-index",
        "--numstat",
        "-M",
        "--find-copies-harder",
        path_old.as_posix(),
        path_new.as_posix(),
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
        clean_path = parse_git_rename_path(file_path_raw, path_old, path_new)

        stats["files"][str(clean_path)] = {
            "insertions": insertions,
            "deletions": deletions,
            "total": insertions + deletions,
        }

        stats["total_insertions"] += insertions
        stats["total_deletions"] += deletions

    return stats

def parse_git_rename_path(raw_path: str, path_old: Path, path_new: Path) -> Path:
    """
    辅助函数：把 Git 重命名格式（如 'dir/{old => new}/a.txt'）转换为新目录的相对路径
    """
    # 如果包含 => 说明触发了重命名或复制
    if "=>" in raw_path:
        # 简单粗暴但最有效的方法：因为我们知道新文件的绝对全路径一定在 path_new 目录中，
        # 且 Git 的输出末尾必然包含新文件名，我们直接去新目录做匹配或直接提取 => 后面的有效路径段。
        # 更加健壮的做法是利用正则提取 => 后面的路径部分
        # 比如： "src/{old_dir => new_dir}/file.js" -> "src/new_dir/file.js"
        match = re.search(r"(.*)\{(.*)\s=>\s(.*)\}(.*)", raw_path)
        if match:
            prefix, _, to_path, suffix = match.groups()
            final_str = f"{prefix}{to_path}{suffix}".replace("//", "/").strip()
        else:
            # 形式为 "old.txt => new.txt"
            final_str = raw_path.split("=>")[1].strip()

        # 最终映射为相对新目录的路径
        full_path = Path(final_str)
        if full_path.is_absolute():
            return full_path.relative_to(path_new)
        return full_path
    else:
        # 普通的增加、删除、修改路径
        p = Path(raw_path)
        if p.is_relative_to(path_new):
            return p.relative_to(path_new)
        elif p.is_relative_to(path_old):
            return p.relative_to(path_old)
        return p


# ================= 演示运行 =================
if __name__ == "__main__":
    folder_old = "./sub_repo"
    folder_new = "./main_repo"

    try:
        line_stats = get_diff_line_stats(folder_old, folder_new)
        print("📊 每个文件的变更行数明细：")
        for f_path, info in line_stats["files"].items():
            print(f"📄 文件: {f_path}")
            print(
                f"   增加: {info['insertions']} 行, 删除: {info['deletions']} 行, 总变更: {info['total']} 行"
            )

        print("-" * 30)
        print(f"🔥 总增加行数: {line_stats['total_insertions']}")
        print(f"💧 总删除行数: {line_stats['total_deletions']}")

    except Exception as e:
        print(f"运行失败: {e}")
