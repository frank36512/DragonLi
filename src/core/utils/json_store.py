"""
JSON 持久化工具模块

统一解决两类数据安全问题：
1. 非原子写入：直接 open(path, 'w') 在写一半时崩溃/断电/磁盘满，会留下损坏文件。
   atomic_write_json / atomic_write_text 先写同目录临时文件，再用 os.replace 原子替换。
2. 损坏文件被静默清空：加载 JSON 失败时，把原文件隔离为 .corrupt-<时间戳> 保留证据，
   而不是返回默认空数据后再被后续保存覆盖，造成不可逆的数据丢失。
"""
import json
import os
import tempfile
from datetime import datetime


def atomic_write_json(path, data, *, indent=4, ensure_ascii=False):
    """原子写入 JSON 文件。成功前绝不改动目标文件，失败时清理临时文件并抛出异常。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_" + os.path.basename(path) + "_",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # 某些文件系统（如网络盘）可能不支持 fsync，忽略即可
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(path, text, *, encoding="utf-8"):
    """原子写入文本文件。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_" + os.path.basename(path) + "_",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def read_json_file(path, default=None, *, quarantine_on_error=True):
    """
    安全读取 JSON 文件。

    - 文件不存在：返回 default
    - 解析失败：将损坏文件隔离为 <path>.corrupt-<时间戳>，打印告警并返回 default，
      避免“加载失败 -> 内存中变为空数据 -> 保存时覆盖原文件”的二次数据丢失。
    """
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as e:
        print(f"[json_store] 读取 JSON 失败 {path}: {e}")
        if quarantine_on_error:
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup = f"{path}.corrupt-{stamp}"
                os.replace(path, backup)
                print(f"[json_store] 已将损坏文件隔离为: {backup}")
            except OSError as rename_err:
                print(f"[json_store] 隔离损坏文件失败: {rename_err}")
        return default
