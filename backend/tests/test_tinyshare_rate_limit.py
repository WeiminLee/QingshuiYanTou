import asyncio
from unittest.mock import patch

import pytest

from scripts import sync_daily_tushare as mod


@pytest.mark.asyncio
async def test_tinyshare_request_starts_are_globally_spaced(monkeypatch):
    clock = {"now": 10.0}
    sleeps = []

    class Loop:
        def time(self):
            return clock["now"]

    async def fake_sleep(delay):
        sleeps.append(delay)
        clock["now"] += delay

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: Loop())
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(mod, "TINYSHARE_REQUEST_INTERVAL", 0.25)
    monkeypatch.setattr(mod, "_next_request_at", 0.0)

    await mod._wait_for_tinyshare_slot()
    await mod._wait_for_tinyshare_slot()

    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_tinyshare_429_is_retried_not_reported_as_empty(monkeypatch):
    calls = 0

    async def no_wait():
        return None

    def fetch(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("服务端错误 (429)：请求过于频繁")
        return [{"ts_code": "600000.SH"}]

    monkeypatch.setattr(mod, "_wait_for_tinyshare_slot", no_wait)
    monkeypatch.setattr(mod, "_fetch_tinyshare", fetch)
    with patch.object(mod.asyncio, "sleep", return_value=None):
        rows = await mod._fetch_tinyshare_with_retry("600000.SH", "20260801", "20260826")

    assert calls == 2
    assert rows == [{"ts_code": "600000.SH"}]
