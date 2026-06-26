"""
文件安全模块

参考 DeerFlow uploads/manager.py 的路径安全设计：
1. 文件名净化：防止路径遍历
2. 路径验证：确保文件在允许范围内
3. 路径遍历检测：防止 .. 攻击
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class PathTraversalError(ValueError):
    """路径遍历检测异常"""


# 安全文件名正则：排除路径分隔符和控制字符
_SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9._\-]+$")


def normalize_filename(filename: str) -> str:
    """
    净化文件名，防止路径遍历。

    策略（参考 DeerFlow）：
    1. 只保留 basename（去除目录部分）
    2. 过滤控制字符和危险字符
    3. 防止 . 和 .. 攻击

    Args:
        filename: 原始文件名

    Returns:
        安全的文件名

    Raises:
        ValueError: 文件名为空或不安全
    """
    if not filename:
        raise ValueError("Filename is empty")

    # 只取 basename，去除所有目录部分
    safe = Path(filename).name

    # 防止 . 和 .. 攻击
    if safe in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {filename!r}")

    # 过滤反斜杠（Windows 路径风格）
    if "\\" in safe:
        raise ValueError(f"Filename contains backslash: {filename!r}")

    # 检查文件名长度（UTF-8 编码）
    if len(safe.encode("utf-8")) > 255:
        raise ValueError(f"Filename too long: {len(safe)} chars")

    return safe


def validate_path_traversal(path: Path, base: Path) -> None:
    """
    验证路径在允许的基础目录范围内。

    策略（参考 DeerFlow）：
    使用 Path.resolve() + relative_to() 检测越界。

    Args:
        path: 要验证的路径
        base: 允许的基础目录

    Raises:
        PathTraversalError: 路径越界
    """
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        raise PathTraversalError(f"Path traversal detected: {path} escapes {base}")


def validate_file_path(
    file_path: Path,
    base_dir: Path,
    filename: str | None = None,
) -> Path:
    """
    安全地解析并验证文件路径。

    整合 normalize_filename + validate_path_traversal。

    Args:
        file_path: 文件路径
        base_dir: 允许的基础目录
        filename: 可选，已净化的文件名

    Returns:
        验证后的绝对路径

    Raises:
        ValueError: 文件名不安全
        PathTraversalError: 路径越界
    """
    # 如果提供了 filename，先净化
    if filename:
        safe_name = normalize_filename(filename)
        file_path = base_dir / safe_name
    else:
        # 从 file_path 提取文件名并净化
        safe_name = normalize_filename(file_path.name)
        file_path = file_path.parent / safe_name

    # 验证路径不越界
    validate_path_traversal(file_path, base_dir)

    return file_path.resolve()


def is_safe_filename(filename: str) -> bool:
    """快速检查文件名是否安全"""
    if not filename:
        return False
    safe = Path(filename).name
    if safe in {".", ".."}:
        return False
    if "\\" in safe:
        return False
    return True
