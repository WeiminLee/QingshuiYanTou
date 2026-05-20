"""
sandbox/file_tools — 虚拟路径沙箱文件工具集

参考 DeerFlow deerflow/sandbox/tools.py 的安全模型：
- 虚拟路径前缀：/mnt/user-data/{workspace,uploads,outputs}
- 所有文件操作限定在虚拟路径内，禁止路径遍历（..）
- 路径映射到实际的 backend/static/uploads/ 目录

目录结构（per-request thread_id）：
    backend/static/uploads/{thread_id}/
        workspace/   — 临时工作文件
        uploads/      — 用户上传文件
        outputs/      — 生成的分析报告

安全约束：
- 路径中包含 .. 则拒绝（_reject_path_traversal）
- 实际路径必须在允许根目录下（validate_resolved_path）
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 虚拟路径前缀
VIRTUAL_PREFIX = "/mnt/user-data"
VIRTUAL_WORKSPACE = f"{VIRTUAL_PREFIX}/workspace"
VIRTUAL_UPLOADS = f"{VIRTUAL_PREFIX}/uploads"
VIRTUAL_OUTPUTS = f"{VIRTUAL_PREFIX}/outputs"

# 实际存储根目录（backend/static/uploads/）
_STORAGE_ROOT = Path(__file__).parent.parent.parent.parent.parent / "static" / "uploads"

# 允许的虚拟子目录
_ALLOWED_VIRTUAL_PREFIXES = (VIRTUAL_WORKSPACE, VIRTUAL_UPLOADS, VIRTUAL_OUTPUTS)

# 路径遍历检测
_PATH_TRAVERSAL_RE = re.compile(r"(^|/)\.\.(/|$)")


def _reject_path_traversal(path: str) -> None:
    """路径中包含 .. 则抛出 PermissionError"""
    normalised = path.replace("\\", "/")
    if _PATH_TRAVERSAL_RE.search(normalised):
        raise PermissionError("访问被拒绝：检测到路径遍历（..）")


def _get_thread_id() -> str:
    """从环境变量获取 thread_id，用于隔离不同用户的文件目录。

    thread_id 由 client.py 在调用工具前通过 os.environ 设置。
    如果未设置则使用 "default"（单用户/测试模式）。
    """
    return os.environ.get("REASONING_THREAD_ID", "default")


def _resolve_virtual_path(virtual_path: str) -> Path:
    """
    将虚拟路径映射为实际文件系统路径。

    /mnt/user-data/workspace -> _STORAGE_ROOT/{thread_id}/workspace
    /mnt/user-data/uploads   -> _STORAGE_ROOT/{thread_id}/uploads
    /mnt/user-data/outputs    -> _STORAGE_ROOT/{thread_id}/outputs

    安全检查：
    1. 路径不能包含 ..
    2. 必须在允许的虚拟前缀下
    3. 解析后的实际路径必须在 _STORAGE_ROOT/{thread_id} 下
    """
    _reject_path_traversal(virtual_path)

    # 验证虚拟前缀
    if not virtual_path.startswith(VIRTUAL_PREFIX):
        raise PermissionError(f"仅允许 {VIRTUAL_PREFIX} 路径，当前: {virtual_path}")

    # 解析虚拟子路径
    relative = virtual_path[len(VIRTUAL_PREFIX):].lstrip("/")
    if not relative:
        raise PermissionError(f"虚拟路径不能是根目录: {virtual_path}")

    # 构建实际路径
    thread_id = _get_thread_id()
    actual_root = _STORAGE_ROOT / thread_id

    # 安全边界：确保实际路径在 thread_id 子目录下
    actual = (actual_root / relative).resolve()
    if not str(actual).startswith(str(actual_root.resolve())):
        raise PermissionError("访问被拒绝：路径越界")

    return actual


def _ensure_dir(path: Path) -> None:
    """确保目录存在（递归创建）"""
    path.mkdir(parents=True, exist_ok=True)


# ── 工具实现 ─────────────────────────────────────────────────────────


@tool("ls")
def ls_tool(
    description: Annotated[str, "列出此目录的原因（简短描述）"],
    path: Annotated[str, "要列出的目录绝对路径（虚拟路径，如 /mnt/user-data/workspace）"],
) -> str:
    """列出目录内容（最多2层深度，树状格式）。"""
    try:
        resolved = _resolve_virtual_path(path)
        if not resolved.exists():
            return f"错误：目录不存在: {path}"
        if not resolved.is_dir():
            return f"错误：路径不是目录: {path}"

        _ensure_dir(resolved)

        lines = [f"{path}/"]

        try:
            entries = sorted(resolved.iterdir())
        except PermissionError:
            return f"错误：权限不足，无法读取目录: {path}"

        for entry in entries:
            if entry.is_dir():
                lines.append(f"  {entry.name}/")
                # 第二层（最多）
                try:
                    sub_entries = sorted(entry.iterdir())
                    for sub in sub_entries[:20]:  # 每层最多显示20个
                        suffix = "/" if sub.is_dir() else ""
                        lines.append(f"    {sub.name}{suffix}")
                    if len(sub_entries) > 20:
                        lines.append(f"    ... ({len(sub_entries) - 20} more)")
                except PermissionError:
                    lines.append(f"    (权限不足)")
            else:
                size = _format_size(entry.stat().st_size)
                lines.append(f"  {entry.name}  {size}")

        if len(lines) == 1:
            return f"{path}/\n(empty)"

        return "\n".join(lines)

    except PermissionError as e:
        return f"错误：{e}"
    except Exception as e:
        logger.warning(f"[ls_tool] error: {e}")
        return f"错误：无法列出目录 {path}: {e}"


@tool("read_file")
def read_file_tool(
    description: Annotated[str, "读取此文件的原因（简短描述）"],
    path: Annotated[str, "要读取的文件绝对路径（虚拟路径，如 /mnt/user-data/workspace/analysis.txt）"],
    start_line: Annotated[int | None, "起始行号（1-indexed，包含）"] = None,
    end_line: Annotated[int | None, "结束行号（1-indexed，包含）"] = None,
) -> str:
    """读取文本文件内容，支持行范围截取。"""
    try:
        resolved = _resolve_virtual_path(path)

        if not resolved.exists():
            return f"错误：文件不存在: {path}"
        if not resolved.is_file():
            return f"错误：路径是目录而非文件: {path}"

        try:
            with open(resolved, encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            try:
                with open(resolved, encoding="gbk") as f:
                    content = f.read()
            except Exception:
                return f"错误：文件编码不支持（仅支持 UTF-8/GBK）: {path}"
        except PermissionError:
            return f"错误：权限不足，无法读取文件: {path}"

        if not content:
            return f"(空文件) {path}"

        # 行范围截取
        if start_line is not None or end_line is not None:
            lines = content.splitlines()
            start = (start_line - 1) if start_line else 0
            end = end_line if end_line else len(lines)
            content = "\n".join(lines[start:end])
            header = f"(行 {start_line or 1}–{end_line or len(lines)}) "
        else:
            header = ""

        # 截断超长文件
        MAX_CHARS = 50000
        if len(content) > MAX_CHARS:
            content = content[:MAX_CHARS] + f"\n\n...（内容已截断，原文 {len(content)} 字符）"

        return f"{header}## 文件: {path}\n\n{content}"

    except PermissionError as e:
        return f"错误：{e}"
    except Exception as e:
        logger.warning(f"[read_file_tool] error: {e}")
        return f"错误：读取文件失败 {path}: {e}"


@tool("write_file")
def write_file_tool(
    description: Annotated[str, "写入此文件的原因（简短描述）"],
    path: Annotated[str, "要写入的文件绝对路径（虚拟路径，如 /mnt/user-data/workspace/report.txt）"],
    content: Annotated[str, "要写入的文本内容"],
    append: Annotated[bool, "是否追加模式（默认 False，覆盖）"] = False,
) -> str:
    """写入或追加内容到文本文件。"""
    try:
        resolved = _resolve_virtual_path(path)

        # 确保父目录存在
        _ensure_dir(resolved.parent)

        mode = "a" if append else "w"
        with open(resolved, mode, encoding="utf-8") as f:
            f.write(content)

        action = "追加到" if append else "写入"
        logger.info(f"[write_file] {action}: {path} ({len(content)} chars)")

        return f"✓ {action}文件成功: {path}"

    except PermissionError as e:
        return f"错误：权限不足，无法写入: {e}"
    except OSError as e:
        return f"错误：写入失败 {path}: {e}"
    except Exception as e:
        logger.warning(f"[write_file_tool] error: {e}")
        return f"错误：写入文件失败 {path}: {e}"


# ── 辅助函数 ─────────────────────────────────────────────────────────


def _format_size(size_bytes: int) -> str:
    """将字节数格式化为人类可读大小"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
