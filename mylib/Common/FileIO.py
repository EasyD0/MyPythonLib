from dataclasses import asdict
from pathlib import Path

import json

from ..LogSet import log_set

logger = log_set(__name__)


def cleanDir(dir: str | Path):
    """
    清空目录下所有文件和文件夹
    """
    dir = Path(dir)
    for item in dir.iterdir():
        if item.is_file():
            item.unlink(missing_ok=True)
        elif item.is_dir():
            cleanDir(item)
            item.rmdir()
        else:
            print(f"未知类型: {item}")
            item.unlink(missing_ok=True)


def save_to_json(obj, json_path: str | Path):
    """
    保存对象到json文件, 将自动检查对象是否有to_json或to_dict方法
    如果没有, 则尝试使用asdict转换为字典
    如果转换失败, 则抛出异常
    """
    if isinstance(obj, dict | list):
        data = obj
    elif hasattr(obj, "to_json"):
        data = obj.to_json()
    elif hasattr(obj, "to_dict"):
        data = obj.to_dict()
    else:
        try:
            data = asdict(obj)
        except Exception:
            raise TypeError(f"对象类型 {type(obj)} 不支持转换为json")

    json_path = Path(json_path).resolve()
    if json_path.exists():
        logger.warning(f"文件 {json_path} 已存在，将覆盖")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_from_json(json_path: str | Path):
    """
    从json文件加载对象
    """
    json_path = Path(json_path).resolve()
    if not json_path.exists():
        logger.error(f"文件 {json_path} 不存在")
        return None
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data
