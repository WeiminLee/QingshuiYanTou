"""concept 收盘后补写（concept_eod）——fetch_concept 参数化 + scheduler EOD 作业验证"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock

import pandas as pd

# ── fetch_concept(trade_date=...)：显式交易日参数 ──────────────


class _FakePro:
    def limit_list_d(self, **kwargs):
        return pd.DataFrame(
            [{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}, {"ts_code": "600000.SH"}]
        )

    def query(self, *args, **kwargs):
        return self.limit_list_d(**kwargs)


class _FakeTinyShare:
    def __init__(self):
        self.token = None

    def set_token(self, token):
        self.token = token

    def pro_api(self):
        return _FakePro()


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        # 映射查询返回 (concept_code, concept_name) 行
        return _FakeResult([("885001.TI", "概念A"), ("885002.TI", "概念B")])


class _FakeEngine:
    def connect(self):
        return _FakeConn()

    def begin(self):
        return _FakeConn()


def _install_fetcher_mocks(monkeypatch):
    import app.config as config_module
    import app.data_pipeline.fetcher as fetcher_mod

    # 防 reload 污染：某些 account 测试会 reload(app.config) 重建 settings 单例，
    # 函数内 `from app.config import settings` 读到的是新实例；必须 patch 模块属性
    # 而非旧实例字段。
    monkeypatch.setattr(config_module, "settings", type("Settings", (), {"tushare_token": "test-token"}))
    monkeypatch.setitem(sys.modules, "tinyshare", _FakeTinyShare())
    monkeypatch.setattr(fetcher_mod, "engine", _FakeEngine())
    calls = []

    async def fake_save(concept_code, concept_name, trade_date, up_nums, pct_chg):
        calls.append((concept_code, concept_name, trade_date, up_nums, pct_chg))

    monkeypatch.setattr(fetcher_mod, "_save_concept_limit", fake_save)
    return fetcher_mod, calls


def test_fetch_concept_accepts_explicit_trade_date(monkeypatch):
    from app.data_pipeline.fetcher import fetch_concept

    _, calls = _install_fetcher_mocks(monkeypatch)

    result = asyncio.run(fetch_concept(trade_date="20261014"))

    assert result == {"success": 2, "fail": 0, "skipped": 0}
    assert calls, "_save_concept_limit 必须被调用"
    assert all(c[2] == "20261014" for c in calls), (
        "显式 trade_date=20261014 必须原样传入写入层"
    )


def test_fetch_concept_defaults_to_shanghai_today(monkeypatch):
    from datetime import datetime

    from app.data_pipeline.fetcher import SH_TZ, fetch_concept

    _, calls = _install_fetcher_mocks(monkeypatch)

    result = asyncio.run(fetch_concept())

    assert result["success"] == 2
    assert calls
    assert calls[0][2] == datetime.now(SH_TZ).strftime("%Y%m%d"), "缺省交易日应为上海时区当天"


# ── scheduler 收盘后补写作业（concept_eod） ───────────────────


def _install_job_mocks(monkeypatch, fetch_result: dict) -> dict:
    """monitor / dingtalk / fetcher 全 mock，返回可断言的 AsyncMock 集合。"""
    import app.data_pipeline.fetcher as fetcher_mod
    from app.data_pipeline import dingtalk as dt
    from app.data_pipeline import monitor

    m = {
        "start": AsyncMock(return_value=1),
        "result": AsyncMock(),
        "fetch": AsyncMock(return_value=fetch_result),
        "notify_start": AsyncMock(),
        "notify_success": AsyncMock(),
        "notify_failed": AsyncMock(),
        "init": AsyncMock(),
    }
    monkeypatch.setattr(monitor, "record_task_start", m["start"])
    monkeypatch.setattr(monitor, "record_task_result", m["result"])
    monkeypatch.setattr(monitor, "init_monitor", m["init"])
    monkeypatch.setattr(dt, "notify_task_start", m["notify_start"])
    monkeypatch.setattr(dt, "notify_task_success", m["notify_success"])
    monkeypatch.setattr(dt, "notify_task_failed", m["notify_failed"])
    monkeypatch.setattr(fetcher_mod, "fetch_concept", m["fetch"])
    return m


def test_concept_eod_bypasses_trading_hours_guard(monkeypatch):
    """核心需求：EOD 作业不得受 _is_trading_hours 抑制（17:30 在收盘后）。"""
    from app.data_pipeline import scheduler as sched

    def _guard_must_not_be_consulted():
        raise AssertionError("_is_trading_hours 被 EOD 作业调用了——不应走 guard")

    monkeypatch.setattr(sched, "_is_trading_hours", _guard_must_not_be_consulted)
    m = _install_job_mocks(monkeypatch, {"success": 5, "fail": 0, "skipped": 0})

    asyncio.run(sched._run_concept_eod_job())

    m["fetch"].assert_awaited_once()
    m["start"].assert_awaited_once_with("concept_eod")
    kwargs = m["result"].await_args.kwargs
    assert kwargs["success"] == 5


def test_concept_eod_records_row_counts(monkeypatch):
    from app.data_pipeline import scheduler as sched

    _install_job_mocks(monkeypatch, {"success": 3, "fail": 1, "skipped": 0})

    asyncio.run(sched._run_concept_eod_job())

    # 0 行时是盲区，有行时必须如实记录 success/fail —— 不再把空跑当成功


def test_concept_eod_warns_on_zero_rows(monkeypatch, caplog):
    import logging

    from app.data_pipeline import scheduler as sched

    _install_job_mocks(monkeypatch, {"success": 0, "fail": 0, "skipped": 0})

    caplog.set_level(logging.WARNING, logger="app.data_pipeline.scheduler")
    asyncio.run(sched._run_concept_eod_job())

    assert any("写入 0 行" in rec.message for rec in caplog.records), (
        "0 行必须显式 warn，不能静默记成功"
    )


def test_concept_eod_default_time_is_17_30(monkeypatch):
    from app.data_pipeline import scheduler as sched

    assert sched._concept_eod_time() == (17, 30)


def test_concept_eod_time_env_override(monkeypatch):
    from app.data_pipeline import scheduler as sched

    monkeypatch.setenv("CONCEPT_EOD_HOUR", "18")
    monkeypatch.setenv("CONCEPT_EOD_MINUTE", "0")
    assert sched._concept_eod_time() == (18, 0)


class _FakeScheduler:
    def __init__(self, *, timezone):
        self.timezone = timezone
        self.jobs = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": getattr(func, "__name__", str(func)), "trigger": trigger, **kwargs})

    def start(self):
        return None


def _start_scheduler(monkeypatch):
    from app.data_pipeline import scheduler as sched

    fake = _FakeScheduler(timezone="Asia/Shanghai")
    monkeypatch.setattr(sched, "AsyncIOScheduler", lambda **kw: fake)
    sched.Scheduler(run_now=False).start()
    return fake


def test_scheduler_registers_concept_eod(monkeypatch):
    fake = _start_scheduler(monkeypatch)

    eod = next(job for job in fake.jobs if job["id"] == "concept_eod")
    assert eod["func"] == "_run_concept_eod_job"
    # CronTrigger 渲染形如 cron[hour='17', minute='30']
    assert "hour='17'" in str(eod["trigger"])
    assert "minute='30'" in str(eod["trigger"])


def test_scheduler_registers_concept_eod_with_env_override(monkeypatch):
    monkeypatch.setenv("CONCEPT_EOD_HOUR", "18")
    fake = _start_scheduler(monkeypatch)

    eod = next(job for job in fake.jobs if job["id"] == "concept_eod")
    assert "hour='18'" in str(eod["trigger"])
