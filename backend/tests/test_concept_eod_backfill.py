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
        self.url = ""

    def set_token(self, token):
        self.token = token

    def set_url(self, url):
        self.url = url

    def get_url(self):
        return self.url

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
    from app.data_pipeline import scheduler as sched

    m = {
        "start": AsyncMock(return_value=1),
        "result": AsyncMock(),
        "fetch": AsyncMock(return_value=fetch_result),
        "notify_start": AsyncMock(),
        "notify_success": AsyncMock(),
        "notify_failed": AsyncMock(),
        "init": AsyncMock(),
        "has_date": AsyncMock(return_value=False),
        "is_trading": AsyncMock(return_value=True),
        "missing": AsyncMock(return_value=None),
        "kline_gap": AsyncMock(return_value=None),
    }
    monkeypatch.setattr(monitor, "record_task_start", m["start"])
    monkeypatch.setattr(monitor, "record_task_result", m["result"])
    monkeypatch.setattr(monitor, "init_monitor", m["init"])
    monkeypatch.setattr(dt, "notify_task_start", m["notify_start"])
    monkeypatch.setattr(dt, "notify_task_success", m["notify_success"])
    monkeypatch.setattr(dt, "notify_task_failed", m["notify_failed"])
    monkeypatch.setattr(fetcher_mod, "fetch_concept", m["fetch"])
    monkeypatch.setattr(sched, "_concept_limit_has_date", m["has_date"])
    monkeypatch.setattr(sched, "_is_trading_day_by_daily_data", m["is_trading"])
    monkeypatch.setattr(sched, "_concept_eod_missing_trade_date", m["missing"])
    monkeypatch.setattr(sched, "_weekday_kline_gap", m["kline_gap"])
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


def test_concept_eod_zero_rows_is_failure_not_success(monkeypatch):
    """交易日确认后写入 0 行必须记失败并告警，不能再记 SUCCESS。"""
    from app.data_pipeline import scheduler as sched
    from app.data_pipeline.monitor import TaskStatus

    m = _install_job_mocks(monkeypatch, {"success": 0, "fail": 0, "skipped": 0})

    asyncio.run(sched._run_concept_eod_job())

    assert m["result"].await_args.args[1] == TaskStatus.FAILED
    m["notify_success"].assert_not_awaited()
    m["notify_failed"].assert_awaited()


def test_concept_hourly_zero_rows_does_not_record_success(monkeypatch):
    """盘中涨停列表尚未发布时，0 行不得记成概念同步成功。"""
    from app.data_pipeline import scheduler as sched

    m = _install_job_mocks(monkeypatch, {"success": 0, "fail": 0, "skipped": 0})
    monkeypatch.setattr(sched, "_is_trading_hours", lambda: True)

    asyncio.run(sched._run_concept_job())

    m["start"].assert_not_awaited()
    m["result"].assert_not_awaited()
    m["notify_success"].assert_not_awaited()
    m["notify_failed"].assert_not_awaited()


def test_concept_eod_catchup_zero_rows_is_failure(monkeypatch):
    from datetime import date

    from app.data_pipeline import scheduler as sched
    from app.data_pipeline.monitor import TaskStatus

    m = _install_job_mocks(monkeypatch, {"success": 0, "fail": 0, "skipped": 0})
    m["missing"].return_value = date(2026, 10, 16)

    asyncio.run(sched._run_concept_eod_catchup())

    assert m["result"].await_args.args[1] == TaskStatus.FAILED
    m["notify_failed"].assert_awaited()


def test_latest_weekday_without_kline_flags_friday_seen_on_monday():
    from datetime import date

    from app.data_pipeline.scheduler import latest_weekday_without_kline

    # 周一回看：周四有日线、周五没有 → 周五是疑似 K 线失败，不是长假。
    gap = latest_weekday_without_kline(
        date(2026, 10, 19),
        {date(2026, 10, 15)},
        include_today=False,
        lookback_days=4,
    )
    assert gap == date(2026, 10, 16)


def test_latest_weekday_without_kline_stays_quiet_when_window_is_dark():
    from datetime import date

    from app.data_pipeline.scheduler import latest_weekday_without_kline

    # 长假后窗口里没有任何日线：当作休市，不告警。
    gap = latest_weekday_without_kline(
        date(2026, 10, 8),
        set(),
        include_today=False,
        lookback_days=4,
    )
    assert gap is None


def test_latest_weekday_without_kline_ignores_complete_weekend():
    from datetime import date

    from app.data_pipeline.scheduler import latest_weekday_without_kline

    gap = latest_weekday_without_kline(
        date(2026, 10, 18),
        {date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)},
        include_today=True,
        lookback_days=4,
    )
    assert gap is None


def test_concept_eod_alerts_when_weekday_has_no_kline(monkeypatch):
    """无日线不能再当成休市静默跳过：近窗有行情时要记失败。"""
    from datetime import date

    from app.data_pipeline import scheduler as sched
    from app.data_pipeline.monitor import TaskStatus

    m = _install_job_mocks(monkeypatch, {"success": 0, "fail": 0, "skipped": 0})
    m["is_trading"].return_value = False
    m["kline_gap"].return_value = date(2026, 10, 16)

    asyncio.run(sched._run_concept_eod_job())

    m["fetch"].assert_not_awaited()
    assert m["result"].await_args.args[1] == TaskStatus.FAILED
    m["notify_failed"].assert_awaited()


def test_concept_catchup_alerts_kline_gap_without_fetch(monkeypatch):
    from datetime import date

    from app.data_pipeline import scheduler as sched
    from app.data_pipeline.monitor import TaskStatus

    m = _install_job_mocks(monkeypatch, {"success": 4, "fail": 0, "skipped": 0})
    m["kline_gap"].return_value = date(2026, 10, 16)

    asyncio.run(sched._run_concept_eod_catchup())

    m["fetch"].assert_not_awaited()
    assert m["result"].await_args.args[1] == TaskStatus.FAILED
    m["notify_failed"].assert_awaited()


def test_concept_eod_skips_when_today_already_exists(monkeypatch):
    """重试命中即停：当日已入库则不再请求数据源（防授权码竞态）。"""
    from app.data_pipeline import scheduler as sched

    m = _install_job_mocks(monkeypatch, {"success": 0, "fail": 0, "skipped": 0})
    m["has_date"].return_value = True

    asyncio.run(sched._run_concept_eod_job())

    m["fetch"].assert_not_awaited()
    m["start"].assert_not_awaited()


def test_concept_eod_skips_silently_on_non_trading_day(monkeypatch, caplog):
    """非交易日（无日线行）必须静默跳过：不请求数据源、不告警、不写 monitor。"""
    import logging

    from app.data_pipeline import scheduler as sched

    m = _install_job_mocks(monkeypatch, {"success": 0, "fail": 0, "skipped": 0})
    m["is_trading"].return_value = False

    caplog.set_level(logging.INFO, logger="app.data_pipeline.scheduler")
    asyncio.run(sched._run_concept_eod_job())

    m["fetch"].assert_not_awaited()
    m["start"].assert_not_awaited()
    assert not any("写入 0 行" in rec.message for rec in caplog.records), (
        "非交易日不得产生 0 行告警（休市被记成异常）"
    )
    assert any("非交易日" in rec.message for rec in caplog.records)


def test_concept_eod_default_time_is_18_30(monkeypatch):
    from app.data_pipeline import scheduler as sched

    assert sched._concept_eod_time() == (18, 30)


def test_concept_eod_time_env_override(monkeypatch):
    from app.data_pipeline import scheduler as sched

    monkeypatch.setenv("CONCEPT_EOD_HOUR", "18")
    monkeypatch.setenv("CONCEPT_EOD_MINUTE", "0")
    assert sched._concept_eod_time() == (18, 0)


def test_concept_eod_retries_default_and_env(monkeypatch):
    from app.data_pipeline import scheduler as sched

    assert sched._concept_eod_retries() == [(19, 30), (20, 30), (21, 30)]

    monkeypatch.setenv("CONCEPT_EOD_RETRIES", "18:45,19:15")
    assert sched._concept_eod_retries() == [(18, 45), (19, 15)]


def test_concept_eod_catchup_time_default_and_env(monkeypatch):
    from app.data_pipeline import scheduler as sched

    assert sched._concept_eod_catchup_time() == (9, 15)

    monkeypatch.setenv("CONCEPT_EOD_CATCHUP_TIME", "10:00")
    assert sched._concept_eod_catchup_time() == (10, 0)


def test_concept_eod_catchup_skips_when_nothing_missing(monkeypatch):
    """无缺失交易日 → 直接跳过，不请求数据源（非交易日/无漏日的静默路径）。"""
    from app.data_pipeline import scheduler as sched

    m = _install_job_mocks(monkeypatch, {"success": 0, "fail": 0, "skipped": 0})

    asyncio.run(sched._run_concept_eod_catchup())

    m["fetch"].assert_not_awaited()
    m["start"].assert_not_awaited()


def test_concept_eod_catchup_backfills_missing_trade_date(monkeypatch):
    from datetime import date

    from app.data_pipeline import scheduler as sched

    m = _install_job_mocks(monkeypatch, {"success": 7, "fail": 0, "skipped": 0})
    m["missing"].return_value = date(2026, 10, 14)

    asyncio.run(sched._run_concept_eod_catchup())

    m["fetch"].assert_awaited_once_with(trade_date="20261014")
    assert m["start"].await_args.args[0] == "concept_eod_catchup"


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
    # CronTrigger 渲染形如 cron[hour='18', minute='30']
    assert "hour='18'" in str(eod["trigger"])
    assert "minute='30'" in str(eod["trigger"])

    ids = [job["id"] for job in fake.jobs]
    assert "concept_eod_retry_19_30" in ids
    assert "concept_eod_retry_20_30" in ids
    assert "concept_eod_retry_21_30" in ids
    assert "concept_eod_catchup" in ids

    catchup = next(job for job in fake.jobs if job["id"] == "concept_eod_catchup")
    assert catchup["func"] == "_run_concept_eod_catchup"
    assert "hour='9'" in str(catchup["trigger"])
    assert "minute='15'" in str(catchup["trigger"])


def test_scheduler_registers_concept_eod_with_env_override(monkeypatch):
    monkeypatch.setenv("CONCEPT_EOD_HOUR", "18")
    monkeypatch.setenv("CONCEPT_EOD_RETRIES", "19:00,20:00")
    fake = _start_scheduler(monkeypatch)

    eod = next(job for job in fake.jobs if job["id"] == "concept_eod")
    assert "hour='18'" in str(eod["trigger"])
    ids = [job["id"] for job in fake.jobs]
    assert "concept_eod_retry_19_00" in ids
    assert "concept_eod_retry_20_00" in ids
    assert "concept_eod_retry_19_30" not in ids
