"""
测试异步钉钉通知模块 — 消除同步 HTTP 阻塞

验证：
1. 所有公共函数均为 async def
2. _send 使用 httpx.AsyncClient（非 httpx.Client）
3. 超时语义保持（10s）
4. 错误处理保持（try/except，返回 False）
5. 配置/签名/未配置跳过等逻辑保持不变
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDingtalkModuleIsAsync:
    """验证 dingtalk 模块公共函数均为 async"""

    def test_send_text_is_async(self):
        from app.data_pipeline.dingtalk import send_text

        assert __import__("inspect").iscoroutinefunction(send_text), "send_text 必须是 async"

    def test_send_markdown_is_async(self):
        from app.data_pipeline.dingtalk import send_markdown

        assert __import__("inspect").iscoroutinefunction(send_markdown), "send_markdown 必须是 async"

    def test_notify_task_start_is_async(self):
        from app.data_pipeline.dingtalk import notify_task_start

        assert __import__("inspect").iscoroutinefunction(notify_task_start), "notify_task_start 必须是 async"

    def test_notify_task_success_is_async(self):
        from app.data_pipeline.dingtalk import notify_task_success

        assert __import__("inspect").iscoroutinefunction(notify_task_success), "notify_task_success 必须是 async"

    def test_notify_task_failed_is_async(self):
        from app.data_pipeline.dingtalk import notify_task_failed

        assert __import__("inspect").iscoroutinefunction(notify_task_failed), "notify_task_failed 必须是 async"

    def test_notify_alert_is_async(self):
        from app.data_pipeline.dingtalk import notify_alert

        assert __import__("inspect").iscoroutinefunction(notify_alert), "notify_alert 必须是 async"

    def test_send_is_async(self):
        from app.data_pipeline.dingtalk import _send

        assert __import__("inspect").iscoroutinefunction(_send), "_send 必须是 async"


class TestDingtalkSend:
    """测试异步 _send 函数"""

    @pytest.mark.asyncio
    async def test_send_uses_async_client(self, monkeypatch):
        """
        场景：发送消息到钉钉
        期望：使用 httpx.AsyncClient，而非 httpx.Client
        """
        from app.data_pipeline import dingtalk

        # 设置配置，让 is_configured 返回 True
        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.return_value = MagicMock(
            json=lambda: {"errcode": 0, "errmsg": "ok"},
        )

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        with patch.object(dingtalk.httpx, "AsyncClient", return_value=async_client):
            result = await dingtalk.send_text("test message")

        assert result is True
        async_client_post.assert_called_once()
        # 验证 POST 请求内容
        call_kwargs = async_client_post.call_args.kwargs
        assert call_kwargs["json"]["msgtype"] == "text"
        assert call_kwargs["json"]["text"]["content"] == "test message"

    @pytest.mark.asyncio
    async def test_send_timeout_preserved(self, monkeypatch):
        """
        场景：验证 timeout 参数保持 10s
        期望：AsyncClient(timeout=10) 被调用
        """
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.return_value = MagicMock(
            json=lambda: {"errcode": 0, "errmsg": "ok"},
        )

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        client_kwargs = {}

        def tracking_async_client(**kwargs):
            client_kwargs.update(kwargs)
            return async_client

        with patch.object(dingtalk.httpx, "AsyncClient", new=tracking_async_client):
            await dingtalk.send_text("test")

        assert client_kwargs.get("timeout") == 10, f"timeout 应为 10，实际为 {client_kwargs.get('timeout')}"

    @pytest.mark.asyncio
    async def test_send_failure_returns_false(self, monkeypatch):
        """
        场景：钉钉返回错误码
        期望：返回 False，不抛异常
        """
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.return_value = MagicMock(
            json=lambda: {"errcode": 400, "errmsg": "invalid token"},
        )

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        with patch.object(dingtalk.httpx, "AsyncClient", return_value=async_client):
            result = await dingtalk.send_text("test")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_exception_returns_false(self, monkeypatch):
        """
        场景：网络异常
        期望：返回 False，不抛异常到调用者
        """
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.side_effect = __import__("httpx").ConnectError("connection refused")

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        with patch.object(dingtalk.httpx, "AsyncClient", return_value=async_client):
            result = await dingtalk.send_text("test")

        assert result is False

    @pytest.mark.asyncio
    async def test_not_configured_returns_false(self, monkeypatch):
        """
        场景：未配置钉钉 webhook
        期望：直接返回 False，不发起 HTTP 请求
        """
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "")

        with patch.object(dingtalk.httpx, "AsyncClient") as mock_client:
            result = await dingtalk.send_text("test")

        assert result is False
        mock_client.assert_not_called()


class TestDingtalkSyncHelpers:
    """同步辅助函数保持原样"""

    def test_is_configured_detects_missing_url(self, monkeypatch):
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "")
        assert dingtalk.is_configured() is False

    def test_is_configured_detects_valid_url(self, monkeypatch):
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")
        assert dingtalk.is_configured() is True

    def test_generate_sign_only_uses_sync(self, monkeypatch):
        """签名生成函数是纯计算，无需 async"""
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "test-secret")
        timestamp, sign = dingtalk._generate_sign("test-secret")
        assert timestamp
        assert sign

    def test_get_webhook_url_with_secret(self, monkeypatch):
        """带加签时 URL 会附加 timestamp 和 sign 参数"""
        import re

        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "test-secret")

        url = dingtalk._get_webhook_url()
        assert "timestamp=" in url
        assert "sign=" in url


class TestDingtalkMarkdown:
    """测试 Markdown 消息格式"""

    @pytest.mark.asyncio
    async def test_send_markdown_format(self, monkeypatch):
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.return_value = MagicMock(
            json=lambda: {"errcode": 0, "errmsg": "ok"},
        )

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        with patch.object(dingtalk.httpx, "AsyncClient", return_value=async_client):
            result = await dingtalk.send_markdown("测试标题", "测试内容")

        assert result is True
        call_kwargs = async_client_post.call_args.kwargs
        assert call_kwargs["json"]["msgtype"] == "markdown"
        assert call_kwargs["json"]["markdown"]["title"] == "测试标题"

    @pytest.mark.asyncio
    async def test_notify_task_start_calls_send_text(self, monkeypatch):
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.return_value = MagicMock(
            json=lambda: {"errcode": 0, "errmsg": "ok"},
        )

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        with patch.object(dingtalk.httpx, "AsyncClient", return_value=async_client):
            result = await dingtalk.notify_task_start("测试任务")

        assert result is True
        call_kwargs = async_client_post.call_args.kwargs
        assert "测试任务" in call_kwargs["json"]["text"]["content"]

    @pytest.mark.asyncio
    async def test_notify_task_success_calls_send_markdown(self, monkeypatch):
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.return_value = MagicMock(
            json=lambda: {"errcode": 0, "errmsg": "ok"},
        )

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        with patch.object(dingtalk.httpx, "AsyncClient", return_value=async_client):
            result = await dingtalk.notify_task_success("测试任务", 10, 8, 2)

        assert result is True

    @pytest.mark.asyncio
    async def test_notify_task_failed_calls_send_markdown(self, monkeypatch):
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.return_value = MagicMock(
            json=lambda: {"errcode": 0, "errmsg": "ok"},
        )

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        with patch.object(dingtalk.httpx, "AsyncClient", return_value=async_client):
            result = await dingtalk.notify_task_failed("测试任务", "超时")

        assert result is True

    @pytest.mark.asyncio
    async def test_notify_alert_calls_send_markdown(self, monkeypatch):
        from app.data_pipeline import dingtalk

        monkeypatch.setattr(dingtalk, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send")
        monkeypatch.setattr(dingtalk, "DINGTALK_SECRET", "")

        async_client_post = AsyncMock()
        async_client_post.return_value = MagicMock(
            json=lambda: {"errcode": 0, "errmsg": "ok"},
        )

        async_client = MagicMock(spec=__import__("httpx").AsyncClient)
        async_client.__aenter__.return_value.post = async_client_post

        with patch.object(dingtalk.httpx, "AsyncClient", return_value=async_client):
            result = await dingtalk.notify_alert("error", "测试任务", "告警信息")

        assert result is True


class TestSchedulerAwaitsDingtalk:
    """验证 scheduler 对 dingtalk 的调用使用了 await"""

    def test_reports_job_awaits_dingtalk(self):
        import inspect

        from app.data_pipeline import scheduler

        src = inspect.getsource(scheduler._run_report_job)
        assert "await notify_task_start" in src
        assert "await notify_task_success" in src
        assert "await notify_task_failed" in src
        assert "notify_task_start(" not in [line.strip() for line in src.split("\n") if "notify" in line]

    def test_concept_job_awaits_dingtalk(self):
        import inspect

        from app.data_pipeline import scheduler

        src = inspect.getsource(scheduler._run_concept_job)
        assert "await notify_task" in src

    def test_irm_job_awaits_dingtalk(self):
        import inspect

        from app.data_pipeline import scheduler

        src = inspect.getsource(scheduler._run_irm_job)
        assert "await notify_task" in src

    def test_cninfo_job_awaits_dingtalk(self):
        import inspect

        from app.data_pipeline import scheduler

        src = inspect.getsource(scheduler._run_cninfo_job)
        assert "await notify_task" in src

    def test_kline_job_awaits_dingtalk(self):
        import inspect

        from app.data_pipeline import scheduler

        src = inspect.getsource(scheduler._run_kline_job)
        assert "await notify_task" in src

    def test_sync_stocks_job_awaits_dingtalk(self):
        import inspect

        from app.data_pipeline import scheduler

        src = inspect.getsource(scheduler._run_sync_stocks_job)
        assert "await notify_task" in src

    def test_batch_reindex_job_awaits_dingtalk(self):
        import inspect

        from app.data_pipeline import scheduler

        src = inspect.getsource(scheduler._run_batch_reindex_job)
        assert "await notify_task" in src


class TestMonitorAwaitsDingtalk:
    """验证 monitor 对 dingtalk 的调用使用了 await"""

    def test_check_and_send_alerts_awaits_notify_alert(self):
        import inspect

        from app.data_pipeline import monitor

        src = inspect.getsource(monitor.check_and_send_alerts)
        # 确认有 await notify_alert 调用
        assert "await notify_alert(" in src
        # 确认没有同步的 notify_alert 调用（排除 import 行）
        call_lines = [l.strip() for l in src.split("\n") if "notify_alert(" in l]
        assert all("await" in l for l in call_lines), f"存在同步 notify_alert 调用: {call_lines}"