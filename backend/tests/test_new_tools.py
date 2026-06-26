"""
tests/test_new_tools.py — Phase 2: 新工具单元测试

覆盖：
- web_fetch（Jina AI）
- sandbox 文件工具（ls/read_file/write_file）
- ask_clarification 澄清工具
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── web_fetch ────────────────────────────────────────────────────────────────


class TestWebFetchTool:
    """web_fetch 工具测试"""

    def test_web_fetch_url_validation(self):
        """非 http/https URL 应返回错误"""
        from app.reasoning.tools.search.web_fetch import web_fetch

        result = web_fetch.invoke({"url": "file:///etc/passwd"})
        assert "错误" in result
        assert "http/https" in result

    def test_web_fetch_missing_url(self):
        """空 URL 应返回错误"""
        from app.reasoning.tools.search.web_fetch import web_fetch

        result = web_fetch.invoke({"url": ""})
        assert "错误" in result

    def test_web_fetch_timeout_param(self):
        """timeout 参数应正确传递"""
        from app.reasoning.tools.search.web_fetch import web_fetch

        # timeout=0 触发 httpx 快速超时
        result = web_fetch.invoke({"url": "https://httpbin.org/delay/10", "timeout": 1})
        assert "超时" in result or "错误" in result

    @patch("httpx.Client")
    def test_web_fetch_success(self, mock_client_class):
        """成功抓取时应返回格式化内容"""
        from app.reasoning.tools.search.web_fetch import web_fetch

        mock_response = MagicMock()
        mock_response.text = "# Hello World\n\n这是正文内容"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = web_fetch.invoke({"url": "https://example.com/article"})
        assert "网页内容" in result
        assert "example.com" in result
        assert "这是正文内容" in result


# ── sandbox file tools ───────────────────────────────────────────────────────


class TestSandboxSecurity:
    """sandbox 安全模型测试"""

    def test_path_traversal_blocked(self):
        """路径包含 .. 应被拒绝"""
        from app.reasoning.tools.sandbox.file_tools import _reject_path_traversal

        with pytest.raises(PermissionError, match="路径遍历"):
            _reject_path_traversal("/mnt/user-data/workspace/../../../etc/passwd")

        with pytest.raises(PermissionError, match="路径遍历"):
            _reject_path_traversal("/mnt/user-data/../uploads/secret.txt")

    def test_only_virtual_prefix_allowed(self):
        """非虚拟路径前缀应被拒绝"""
        from app.reasoning.tools.sandbox.file_tools import _resolve_virtual_path

        with pytest.raises(PermissionError, match="仅允许"):
            _resolve_virtual_path("/etc/passwd")

        with pytest.raises(PermissionError, match="仅允许"):
            _resolve_virtual_path("/home/user/file.txt")


class TestLsTool:
    """ls_tool 测试"""

    def test_ls_nonexistent_dir(self):
        """不存在的目录应返回错误"""
        from app.reasoning.tools.sandbox.file_tools import ls_tool

        # 设置 thread_id
        with patch.dict(os.environ, {"REASONING_THREAD_ID": "test_ls_001"}):
            result = ls_tool.invoke(
                {
                    "description": "测试",
                    "path": "/mnt/user-data/workspace/nonexistent_dir_xyz",
                }
            )
            assert "错误" in result or "不存在" in result

    def test_ls_empty_dir(self):
        """空目录应返回 (empty)"""
        from app.reasoning.tools.sandbox.file_tools import ls_tool

        with tempfile.TemporaryDirectory() as td:
            with patch("app.reasoning.tools.sandbox.file_tools._STORAGE_ROOT", Path(td)):
                with patch.dict(os.environ, {"REASONING_THREAD_ID": "test_ls_002"}):
                    # 创建 workspace 目录
                    ws = Path(td) / "test_ls_002" / "workspace"
                    ws.mkdir(parents=True)

                    result = ls_tool.invoke(
                        {
                            "description": "测试",
                            "path": "/mnt/user-data/workspace",
                        }
                    )
                    assert "empty" in result or "(empty)" in result


class TestReadFileTool:
    """read_file_tool 测试"""

    def test_read_nonexistent_file(self):
        """不存在的文件应返回错误"""
        from app.reasoning.tools.sandbox.file_tools import read_file_tool

        with patch.dict(os.environ, {"REASONING_THREAD_ID": "test_read_001"}):
            result = read_file_tool.invoke(
                {
                    "description": "测试",
                    "path": "/mnt/user-data/workspace/nonexistent.txt",
                }
            )
            assert "错误" in result or "不存在" in result

    def test_read_file_success(self):
        """成功读取文件"""
        from app.reasoning.tools.sandbox.file_tools import read_file_tool

        with tempfile.TemporaryDirectory() as td:
            with patch("app.reasoning.tools.sandbox.file_tools._STORAGE_ROOT", Path(td)):
                with patch.dict(os.environ, {"REASONING_THREAD_ID": "test_read_002"}):
                    # 创建文件
                    f = Path(td) / "test_read_002" / "workspace" / "hello.txt"
                    f.parent.mkdir(parents=True)
                    f.write_text("Hello World", encoding="utf-8")

                    result = read_file_tool.invoke(
                        {
                            "description": "测试读取",
                            "path": "/mnt/user-data/workspace/hello.txt",
                        }
                    )
                    assert "Hello World" in result
                    assert "hello.txt" in result

    def test_read_file_line_range(self):
        """行范围截取应正确工作"""
        from app.reasoning.tools.sandbox.file_tools import read_file_tool

        with tempfile.TemporaryDirectory() as td:
            with patch("app.reasoning.tools.sandbox.file_tools._STORAGE_ROOT", Path(td)):
                with patch.dict(os.environ, {"REASONING_THREAD_ID": "test_read_003"}):
                    # 创建多行文件
                    content = "\n".join([f"line {i}" for i in range(1, 21)])
                    f = Path(td) / "test_read_003" / "workspace" / "multiline.txt"
                    f.parent.mkdir(parents=True)
                    f.write_text(content, encoding="utf-8")

                    result = read_file_tool.invoke(
                        {
                            "description": "测试行范围",
                            "path": "/mnt/user-data/workspace/multiline.txt",
                            "start_line": 5,
                            "end_line": 10,
                        }
                    )
                    assert "line 5" in result
                    assert "line 10" in result
                    # "line 1\n" 不应出现在文件内容中（行1-4不在范围内）
                    assert "line 1\n" not in result and "line 2\n" not in result


class TestWriteFileTool:
    """write_file_tool 测试"""

    def test_write_file_success(self):
        """成功写入文件"""
        from app.reasoning.tools.sandbox.file_tools import write_file_tool

        with tempfile.TemporaryDirectory() as td:
            with patch("app.reasoning.tools.sandbox.file_tools._STORAGE_ROOT", Path(td)):
                with patch.dict(os.environ, {"REASONING_THREAD_ID": "test_write_001"}):
                    result = write_file_tool.invoke(
                        {
                            "description": "测试写入",
                            "path": "/mnt/user-data/workspace/test.txt",
                            "content": "Hello from test",
                        }
                    )
                    assert "成功" in result

                    # 验证文件存在
                    f = Path(td) / "test_write_001" / "workspace" / "test.txt"
                    assert f.exists()
                    assert f.read_text(encoding="utf-8") == "Hello from test"

    def test_write_file_append_mode(self):
        """追加模式应正确工作"""
        from app.reasoning.tools.sandbox.file_tools import write_file_tool

        with tempfile.TemporaryDirectory() as td:
            with patch("app.reasoning.tools.sandbox.file_tools._STORAGE_ROOT", Path(td)):
                with patch.dict(os.environ, {"REASONING_THREAD_ID": "test_write_002"}):
                    f = Path(td) / "test_write_002" / "workspace" / "append.txt"
                    f.parent.mkdir(parents=True)
                    f.write_text("Line 1\n", encoding="utf-8")

                    write_file_tool.invoke(
                        {
                            "description": "测试追加",
                            "path": "/mnt/user-data/workspace/append.txt",
                            "content": "Line 2\n",
                            "append": True,
                        }
                    )

                    content = f.read_text(encoding="utf-8")
                    assert "Line 1" in content
                    assert "Line 2" in content


# ── ask_clarification ────────────────────────────────────────────────────────


class TestAskClarificationTool:
    """ask_clarification 工具测试"""

    def test_ask_clarification_returns_pending_message(self):
        """ask_clarification 应返回等待提示"""
        from app.reasoning.tools.builtins.clarification import (
            ask_clarification,
            clear_clarifications,
        )

        clear_clarifications()

        result = ask_clarification.invoke(
            {
                "question": "请问您想分析哪只股票？",
                "clarification_type": "missing_info",
            }
        )
        assert "澄清请求" in result
        assert "请问您想分析哪只股票？" in result

    def test_push_and_pop_clarification(self):
        """push_clarification / pop_clarification 应成对工作"""
        from app.reasoning.tools.builtins.clarification import (
            clear_clarifications,
            pop_clarification,
            push_clarification,
        )

        clear_clarifications()

        clarification_id = push_clarification(
            question="测试问题？",
            clarification_type="ambiguous",
            options=["选项A", "选项B"],
            context="测试上下文",
        )

        item = pop_clarification(clarification_id)
        assert item is not None
        assert item["question"] == "测试问题？"
        assert item["clarification_type"] == "ambiguous"
        assert item["options"] == ["选项A", "选项B"]
        assert item["context"] == "测试上下文"

    def test_pop_nonexistent_returns_none(self):
        """pop 不存在的 id 应返回 None"""
        from app.reasoning.tools.builtins.clarification import pop_clarification

        result = pop_clarification("nonexistent_id_xyz")
        assert result is None

    def test_has_pending_clarification(self):
        """has_pending_clarification 应正确反映队列状态"""
        from app.reasoning.tools.builtins.clarification import (
            clear_clarifications,
            has_pending_clarification,
            pop_clarification,
            push_clarification,
        )

        clear_clarifications()
        assert not has_pending_clarification()

        cid = push_clarification(question="Q?", clarification_type="missing_info")
        assert has_pending_clarification()

        pop_clarification(cid)
        assert not has_pending_clarification()
