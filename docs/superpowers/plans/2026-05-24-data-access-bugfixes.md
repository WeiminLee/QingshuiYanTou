# 数据获取层缺陷修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复数据获取层审计发现的剩余缺陷，使调度启动、限流、baostock 采集、公告历史回填、日志观测和 durable job 重试语义可预测、可测试。

**架构：** 保持现有 `DataFetcher` / `DataSourceClient` / `IngestionJobQueue` 边界，不做横向重构。每个修复先补回归测试，再做最小代码变更；对外部接口失败与真实空数据做语义区分，让上层统计能正确产生 `fail`。

**技术栈：** Python 3.10+、asyncio、pytest、SQLAlchemy async、APScheduler、akshare、baostock、requests。

---

## 文件结构

- 修改：`backend/app/data_pipeline/scheduler.py`
  - 负责调度器启动补跑，移除 `asyncio.get_event_loop()` 对无当前事件循环入口的依赖。
- 修改：`backend/app/data_pipeline/rate_limiter.py`
  - 负责 akshare、巨潮 PDF、巨潮 API、akshare async limiter 的线程安全单例。
- 修改：`backend/app/data_pipeline/data_source.py`
  - 负责同步数据源封装，给 baostock K 线增加可抛错模式，补齐财联社异常日志。
- 修改：`backend/app/data_pipeline/fetcher.py`
  - 负责数据获取编排，隔离 baostock 并发 session，修复 K 线失败统计、历史公告 KG hook、低级别日志。
- 修改：`backend/app/data_pipeline/cninfo_client.py`
  - 负责巨潮分页查询，增加最大页数保护。
- 修改：`backend/app/data_pipeline/job_handlers.py`
  - 负责 durable job 执行结果映射，让 partial fetcher 结果进入可重试状态。
- 修改：`backend/tests/test_phase31_scheduler.py`
  - 覆盖 `_fire_all_once()` 的运行中事件循环行为。
- 修改：`backend/tests/test_reported_bugs.py`
  - 放置跨模块回归测试：限流器单例、日志、K 线错误语义。
- 修改：`backend/tests/test_phase31_fetcher.py`
  - 覆盖全市场 K 线隔离 client 与失败统计。
- 修改：`backend/tests/test_cninfo_client.py`
  - 覆盖历史公告 KG hook 与巨潮分页上限。
- 修改：`backend/tests/test_ingestion_job_worker.py`
  - 更新 durable job partial 映射为可重试 failure 的期望。

## 任务 1：调度器启动补跑事件循环修复

**文件：**
- 修改：`backend/app/data_pipeline/scheduler.py:544-565`
- 测试：`backend/tests/test_phase31_scheduler.py`

- [ ] **步骤 1：编写失败的测试**

在 `backend/tests/test_phase31_scheduler.py` 追加：

```python
def test_fire_all_once_uses_running_loop(monkeypatch):
    from app.data_pipeline import scheduler as sched

    created = []

    async def fake_job():
        return None

    monkeypatch.setattr(sched, "_run_report_job", fake_job)
    monkeypatch.setattr(sched, "_run_concept_job", fake_job)
    monkeypatch.setattr(sched, "_run_kline_job", fake_job)
    monkeypatch.setattr(sched, "_run_irm_enqueue_job", fake_job)
    monkeypatch.setattr(sched, "_run_cninfo_enqueue_job", fake_job)
    monkeypatch.setattr(sched, "_run_ingestion_worker_job", fake_job)
    monkeypatch.setattr(sched, "_run_sync_stocks_job", fake_job)

    async def run_case():
        loop = asyncio.get_running_loop()
        original_create_task = loop.create_task

        def tracking_create_task(coro, *, name=None, context=None):
            task = original_create_task(coro, name=name, context=context)
            created.append(task)
            return task

        monkeypatch.setattr(loop, "create_task", tracking_create_task)
        monkeypatch.setattr(
            sched.asyncio,
            "get_event_loop",
            MagicMock(side_effect=RuntimeError("deprecated path used")),
        )
        sched.Scheduler(run_now=False)._fire_all_once()
        await asyncio.gather(*created)

    asyncio.run(run_case())

    assert len(created) == 7
    sched.asyncio.get_event_loop.assert_not_called()
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_phase31_scheduler.py::test_fire_all_once_uses_running_loop -v
```

预期：FAIL，报错包含 `deprecated path used` 或 `_fire_all_once` 调用了 `get_event_loop`。

- [ ] **步骤 3：编写最少实现代码**

把 `backend/app/data_pipeline/scheduler.py` 中 `_fire_all_once()` 里的 loop 获取替换为：

```python
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("[启动补漏] 无运行中的 asyncio loop，跳过 run_now 补跑")
            return
```

保留后续 `task_specs`、`create_task`、`add_done_callback` 逻辑不变。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd backend
pytest tests/test_phase31_scheduler.py::test_fire_all_once_uses_running_loop tests/test_phase31_scheduler.py::TestFireAllOnceCallback::test_task_exception_logged -v
```

预期：2 passed。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/scheduler.py backend/tests/test_phase31_scheduler.py
git commit -m "fix: use running loop for scheduler startup jobs"
```

## 任务 2：限流器线程安全单例

**文件：**
- 修改：`backend/app/data_pipeline/rate_limiter.py:190-256`
- 测试：`backend/tests/test_reported_bugs.py`

- [ ] **步骤 1：编写失败的测试**

在 `backend/tests/test_reported_bugs.py` 追加：

```python
def test_rate_limiter_singletons_are_thread_safe():
    from app.data_pipeline import rate_limiter

    rate_limiter._akshare_limiter = None
    rate_limiter._cninfo_pdf_limiter = None
    rate_limiter._cninfo_api_limiter = None
    rate_limiter._akshare_async_limiter = None

    def collect(factory):
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            return list(pool.map(lambda _i: factory(), range(64)))

    akshare_instances = collect(rate_limiter.get_akshare_limiter)
    pdf_instances = collect(rate_limiter.get_cninfo_pdf_limiter)
    cninfo_api_instances = collect(rate_limiter.get_cninfo_api_limiter)
    akshare_async_instances = collect(rate_limiter.get_akshare_async_limiter)

    assert len({id(item) for item in akshare_instances}) == 1
    assert len({id(item) for item in pdf_instances}) == 1
    assert len({id(item) for item in cninfo_api_instances}) == 1
    assert len({id(item) for item in akshare_async_instances}) == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_reported_bugs.py::test_rate_limiter_singletons_are_thread_safe -v
```

预期：FAIL，至少 `get_akshare_async_limiter()` 产生多个实例。

- [ ] **步骤 3：编写最少实现代码**

在 `backend/app/data_pipeline/rate_limiter.py` 全局变量区加入：

```python
_limiter_init_lock = threading.Lock()
_akshare_async_limiter: AsyncRateLimiter | None = None
```

替换 `get_akshare_async_limiter()`：

```python
def get_akshare_async_limiter() -> AsyncRateLimiter:
    """获取全局异步版本 akshare 限速器。"""
    global _akshare_async_limiter
    if _akshare_async_limiter is None:
        with _limiter_init_lock:
            if _akshare_async_limiter is None:
                _akshare_async_limiter = AsyncRateLimiter(
                    max_requests=1,
                    window_seconds=1.0,
                    name="akshare-async",
                )
    return _akshare_async_limiter
```

替换 `get_akshare_limiter()`：

```python
def get_akshare_limiter() -> RateLimiter:
    """获取全局 akshare 接口限速器（每秒 1 次，约 60 次/分钟）。"""
    global _akshare_limiter
    if _akshare_limiter is None:
        with _limiter_init_lock:
            if _akshare_limiter is None:
                _akshare_limiter = RateLimiter(
                    max_requests=1,
                    window_seconds=1.0,
                    name="akshare",
                )
    return _akshare_limiter
```

替换 `get_cninfo_pdf_limiter()`：

```python
def get_cninfo_pdf_limiter() -> RateLimiter:
    """获取全局巨潮 PDF 下载限速器（每秒 1 个文件）"""
    global _cninfo_pdf_limiter
    if _cninfo_pdf_limiter is None:
        with _limiter_init_lock:
            if _cninfo_pdf_limiter is None:
                _cninfo_pdf_limiter = RateLimiter(
                    max_requests=1,
                    window_seconds=1.0,
                    name="巨潮PDF下载",
                )
    return _cninfo_pdf_limiter
```

替换 `get_cninfo_api_limiter()`：

```python
def get_cninfo_api_limiter() -> AsyncRateLimiter:
    """获取全局巨潮 API 异步限速器（每秒 1 次请求）。"""
    global _cninfo_api_limiter
    if _cninfo_api_limiter is None:
        with _limiter_init_lock:
            if _cninfo_api_limiter is None:
                _cninfo_api_limiter = AsyncRateLimiter(
                    max_requests=1,
                    window_seconds=1.0,
                    name="cninfo-api",
                )
    return _cninfo_api_limiter
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd backend
pytest tests/test_reported_bugs.py::test_rate_limiter_singletons_are_thread_safe -v
```

预期：1 passed。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/rate_limiter.py backend/tests/test_reported_bugs.py
git commit -m "fix: make data source limiters thread safe"
```

## 任务 3：baostock K 线失败与空数据语义分离

**文件：**
- 修改：`backend/app/data_pipeline/data_source.py:357-421`
- 修改：`backend/app/data_pipeline/fetcher.py:1612-1646`
- 测试：`backend/tests/test_reported_bugs.py`

- [ ] **步骤 1：编写失败的测试**

在 `backend/tests/test_reported_bugs.py` 追加：

```python
def test_stock_kline_fetch_failure_counts_as_fail():
    from app.data_pipeline.fetcher import DataFetcher

    fetcher = DataFetcher()
    fetcher.data_source = MagicMock()
    fetcher.data_source.get_stock_kline.side_effect = RuntimeError("baostock broken")

    result = asyncio.run(
        fetcher.fetch_stock_kline(
            "600000.SH",
            start_date="20260520",
            end_date="20260521",
        )
    )

    assert result == {"total": 0, "success": 0, "skipped": 0, "fail": 1}
```

在同一文件追加：

```python
def test_data_source_stock_kline_can_raise_on_api_error(monkeypatch):
    from app.data_pipeline import data_source as data_source_mod
    from app.data_pipeline.data_source import DataSourceClient

    class FakeResult:
        error_code = "100"
        error_msg = "service unavailable"

        def next(self):
            return False

    fake_bs = MagicMock()
    fake_bs.query_history_k_data_plus.return_value = FakeResult()
    fake_bs.login.return_value = None
    monkeypatch.setattr(data_source_mod, "bs", fake_bs)

    client = DataSourceClient()

    try:
        client.get_stock_kline(
            "600000.SH",
            "20260520",
            "20260521",
            raise_on_error=True,
        )
    except RuntimeError as exc:
        assert "service unavailable" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_reported_bugs.py::test_stock_kline_fetch_failure_counts_as_fail tests/test_reported_bugs.py::test_data_source_stock_kline_can_raise_on_api_error -v
```

预期：FAIL，第一个返回 `fail=0` 或第二个报 `unexpected keyword argument 'raise_on_error'`。

- [ ] **步骤 3：编写最少实现代码**

把 `DataSourceClient.get_stock_kline` 签名改为：

```python
    def get_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
        raise_on_error: bool = False,
    ) -> list[dict[str, Any]]:
```

在 `_ts_to_bs(ts_code)` 的 `except ValueError` 分支替换为：

```python
        except ValueError as e:
            logger.warning("baostock ts_code 转换失败 %s: %s", ts_code, e)
            if raise_on_error:
                raise
            return []
```

把非零返回处理替换为：

```python
            if rs.error_code != "0":
                message = f"baostock {ts_code} 非零返回: {rs.error_code} {rs.error_msg}"
                logger.warning(message)
                if raise_on_error:
                    raise RuntimeError(message)
```

把最外层异常分支替换为：

```python
        except Exception as e:
            logger.warning("获取个股K线 %s 失败: %s", ts_code, e)
            if raise_on_error:
                raise
            return []
```

在 `DataFetcher.fetch_stock_kline()` 中包住抓取调用：

```python
        try:
            records = await asyncio.to_thread(
                self.data_source.get_stock_kline,
                ts_code,
                start_str,
                end_str,
                "3",
                True,
            )
        except Exception as exc:
            logger.warning("个股 %s K线抓取失败: %s", ts_code, exc)
            return {"total": 0, "success": 0, "skipped": 0, "fail": 1}
```

保留后面的 `if not records: return {"total": 0, ... "fail": 0}`，让真实空数据仍是非失败。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd backend
pytest tests/test_reported_bugs.py::test_stock_kline_fetch_failure_counts_as_fail tests/test_reported_bugs.py::test_data_source_stock_kline_can_raise_on_api_error -v
```

预期：2 passed。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/data_source.py backend/app/data_pipeline/fetcher.py backend/tests/test_reported_bugs.py
git commit -m "fix: distinguish stock kline fetch errors from empty data"
```

## 任务 4：全市场 K 线 baostock session 隔离

**文件：**
- 修改：`backend/app/data_pipeline/fetcher.py:1648-1769`
- 测试：`backend/tests/test_phase31_fetcher.py`

- [ ] **步骤 1：编写失败的测试**

在 `backend/tests/test_phase31_fetcher.py` 追加：

```python
def test_fetch_all_stocks_kline_uses_isolated_data_source(monkeypatch):
    import asyncio
    from datetime import date
    from unittest.mock import AsyncMock, MagicMock

    import app.data_pipeline.fetcher as fetcher_mod
    from app.data_pipeline.fetcher import DataFetcher

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, *args, **kwargs):
            return FakeResult()

    fake_engine = MagicMock()
    fake_engine.connect.return_value = FakeConn()
    monkeypatch.setattr(fetcher_mod, "engine", fake_engine)
    monkeypatch.setattr(fetcher_mod, "STOCK_KLINE_SLEEP_BASE", 0)
    monkeypatch.setattr(fetcher_mod, "STOCK_KLINE_SLEEP_JITTER", 0)

    created_clients = []

    class IsolatedClient:
        def __init__(self):
            created_clients.append(self)
            self.logged_out = False

        def get_stock_kline(self, ts_code, start_date, end_date, adjustflag="3", raise_on_error=False):
            assert raise_on_error is True
            return [{"date": "2026-05-22", "close": "10", "preclose": "9"}]

        def _bs_logout(self):
            self.logged_out = True

    monkeypatch.setattr(fetcher_mod, "DataSourceClient", IsolatedClient)

    fetcher = DataFetcher()
    fetcher.data_source = MagicMock()
    fetcher.data_source.get_stocks_basic.return_value = [
        {"ts_code": "600000.SH"},
        {"ts_code": "000001.SZ"},
    ]
    fetcher._save_stock_kline = AsyncMock(return_value=True)

    result = asyncio.run(fetcher.fetch_all_stocks_kline(end_date="20260522"))

    assert result["fail"] == 0
    assert result["success"] == 2
    assert len(created_clients) == 2
    assert all(client.logged_out for client in created_clients)
    fetcher.data_source.get_stock_kline.assert_not_called()
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_phase31_fetcher.py::test_fetch_all_stocks_kline_uses_isolated_data_source -v
```

预期：FAIL，因为当前 worker 使用 `self.data_source.get_stock_kline`。

- [ ] **步骤 3：编写最少实现代码**

在 `backend/app/data_pipeline/fetcher.py` 中 `DataFetcher.fetch_all_stocks_kline()` 内部、`worker` 定义之前加入：

```python
        def fetch_with_isolated_client(code: str, start_str: str, end_str: str) -> list[dict[str, Any]]:
            client = DataSourceClient()
            try:
                return client.get_stock_kline(
                    code,
                    start_str,
                    end_str,
                    raise_on_error=True,
                )
            finally:
                client._bs_logout()
```

在 `worker()` 内删除 `idx % STOCK_KLINE_RECONNECT_EVERY` 的共享 client 重连块，把抓取调用替换为：

```python
                    records = await asyncio.to_thread(
                        fetch_with_isolated_client,
                        code,
                        start_str,
                        end_str,
                    )
```

把 `if not records:` 保持为 skipped。把 `_save_stock_kline` 返回 `False` 的路径计入失败：

```python
                        saved = await self._save_stock_kline(code, trade_date, rec)
                        if saved is True:
                            counters["success"] += 1
                        elif saved is False:
                            counters["fail"] += 1
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd backend
pytest tests/test_phase31_fetcher.py::test_fetch_all_stocks_kline_uses_isolated_data_source tests/test_phase31_fetcher.py::TestPerStockKlineCatchup::test_fetch_all_stocks_uses_per_stock_latest_date -v
```

预期：2 passed。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/fetcher.py backend/tests/test_phase31_fetcher.py
git commit -m "fix: isolate baostock clients during market kline sync"
```

## 任务 5：历史公告 PDF 下载触发 KG 抽取

**文件：**
- 修改：`backend/app/data_pipeline/fetcher.py:1307-1374`
- 测试：`backend/tests/test_cninfo_client.py`

- [ ] **步骤 1：编写失败的测试**

在 `backend/tests/test_cninfo_client.py` 的公告 fetcher 测试类中追加：

```python
    def test_fetch_announcements_history_triggers_kg_after_new_pdf(self):
        """历史公告新下载 PDF 后应触发 KG 抽取 hook。"""
        from app.data_pipeline.fetcher import DataFetcher

        ann = self._build_announcement(
            "id-history-kg",
            "300593",
            "新雷能",
            "2024年年度报告",
        )
        existing = {}
        engine_mock = MagicMock()
        engine_mock.connect = lambda: _FakeConnCM(existing)
        engine_mock.begin = lambda: _FakeConnCM(existing, write=True)

        fetcher = DataFetcher()
        fetcher.cninfo_client = MagicMock()
        fetcher.cninfo_client.get_announcements = AsyncMock(return_value=[ann])
        fetcher.storage = MagicMock()
        fetcher.storage.download_notice = MagicMock(return_value=Path("/tmp/history-kg.pdf"))
        fetcher._on_pdf_download_complete = AsyncMock()

        with patch("app.data_pipeline.fetcher.engine", engine_mock), \
             patch("app.data_pipeline.fetcher.IngestionProgressTracker", _FakeTracker):
            result = asyncio.run(
                fetcher.fetch_announcements_history(
                    start_date="20240517",
                    end_date="20240517",
                )
            )

        assert result["downloaded"] == 1
        fetcher._on_pdf_download_complete.assert_awaited_once_with(
            "id-history-kg",
            Path("/tmp/history-kg.pdf"),
            "300593.SZ",
            "2024年年度报告",
        )
```

在同一测试类中追加：

```python
    def test_fetch_announcements_history_triggers_kg_after_repair_pdf(self):
        """历史公告修复丢失 PDF 后应触发 KG 抽取 hook。"""
        from app.data_pipeline.fetcher import DataFetcher

        ann = self._build_announcement(
            "id-history-repair-kg",
            "300593",
            "新雷能",
            "2024年年度报告",
        )
        missing_path = "/tmp/qingshui-history-missing.pdf"
        Path(missing_path).unlink(missing_ok=True)
        existing = {"id-history-repair-kg": missing_path}
        engine_mock = MagicMock()
        engine_mock.connect = lambda: _FakeConnCM(existing)
        engine_mock.begin = lambda: _FakeConnCM(existing, write=True)

        fetcher = DataFetcher()
        fetcher.cninfo_client = MagicMock()
        fetcher.cninfo_client.get_announcements = AsyncMock(return_value=[ann])
        fetcher.storage = MagicMock()
        fetcher.storage.download_notice = MagicMock(return_value=Path("/tmp/history-repair.pdf"))
        fetcher._on_pdf_download_complete = AsyncMock()

        with patch("app.data_pipeline.fetcher.engine", engine_mock), \
             patch("app.data_pipeline.fetcher.IngestionProgressTracker", _FakeTracker):
            result = asyncio.run(
                fetcher.fetch_announcements_history(
                    start_date="20240517",
                    end_date="20240517",
                )
            )

        assert result["downloaded"] == 1
        fetcher._on_pdf_download_complete.assert_awaited_once()
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_cninfo_client.py::TestFetchAnnouncements::test_fetch_announcements_history_triggers_kg_after_new_pdf tests/test_cninfo_client.py::TestFetchAnnouncements::test_fetch_announcements_history_triggers_kg_after_repair_pdf -v
```

预期：FAIL，`_on_pdf_download_complete` 未被 await。

- [ ] **步骤 3：编写最少实现代码**

在 `fetch_announcements_history()` 已存在公告修复 PDF 的 `updated = await self._update_announcement_file_path(...)` 后加入：

```python
                        await self._on_pdf_download_complete(
                            item["cninfo_id"],
                            repaired_path,
                            item["ts_code"],
                            item["title"],
                        )
```

在历史公告新增路径 `if saved is True:` 下加入：

```python
                if file_path is not None:
                    await self._on_pdf_download_complete(
                        item["cninfo_id"],
                        file_path,
                        item["ts_code"],
                        item["title"],
                    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd backend
pytest tests/test_cninfo_client.py::TestFetchAnnouncements::test_fetch_announcements_history_triggers_kg_after_new_pdf tests/test_cninfo_client.py::TestFetchAnnouncements::test_fetch_announcements_history_triggers_kg_after_repair_pdf -v
```

预期：2 passed。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/fetcher.py backend/tests/test_cninfo_client.py
git commit -m "fix: trigger kg extraction for historical announcement pdfs"
```

## 任务 6：失败日志提升到可观测级别

**文件：**
- 修改：`backend/app/data_pipeline/data_source.py:227-245`
- 修改：`backend/app/data_pipeline/fetcher.py:624-642`
- 修改：`backend/app/data_pipeline/fetcher.py:1807-1838`
- 修改：`backend/app/data_pipeline/fetcher.py:1895-1908`
- 测试：`backend/tests/test_reported_bugs.py`

- [ ] **步骤 1：编写失败的测试**

在 `backend/tests/test_reported_bugs.py` 追加：

```python
def test_cls_telegraph_fetch_error_logs_warning(monkeypatch, caplog):
    from app.data_pipeline import data_source as data_source_mod
    from app.data_pipeline.data_source import DataSourceClient

    def bad_fetch(symbol):
        raise RuntimeError("cls unavailable")

    monkeypatch.setattr(data_source_mod.ak, "stock_info_global_cls", bad_fetch)
    caplog.set_level(logging.WARNING, logger="app.data_pipeline.data_source")

    assert DataSourceClient().get_cls_telegraph() == []
    assert "财联社电报" in caplog.text
    assert "cls unavailable" in caplog.text
```

在同一文件追加：

```python
def test_irm_checkpoint_write_failure_logs_warning(caplog):
    from app.data_pipeline.fetcher import DataFetcher

    fake_db = MagicMock()
    fake_db.__getitem__.side_effect = RuntimeError("mongo down")
    caplog.set_level(logging.WARNING, logger="app.data_pipeline.fetcher")

    with patch("app.data_pipeline.fetcher.get_mongo_db", return_value=fake_db):
        asyncio.run(DataFetcher()._save_irm_checkpoint("600000.SH", success=True))

    assert "IRM checkpoint 写入失败" in caplog.text
    assert "mongo down" in caplog.text
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_reported_bugs.py::test_cls_telegraph_fetch_error_logs_warning tests/test_reported_bugs.py::test_irm_checkpoint_write_failure_logs_warning -v
```

预期：FAIL，因为一个没有日志，一个日志级别是 debug。

- [ ] **步骤 3：编写最少实现代码**

在 `DataSourceClient.get_cls_telegraph()` 中替换异常分支：

```python
        except Exception as e:
            logger.warning("获取财联社电报失败: %s", e)
            return []
```

在 `DataFetcher._save_irm_checkpoint()` 中替换异常分支：

```python
        except Exception as exc:
            logger.warning("IRM checkpoint 写入失败 [%s]: %s", ts_code, exc)
```

在 `async_sync_stocks()` 中替换单条失败日志：

```python
            logger.warning("股票同步失败 %s: %s", ts_code, exc)
```

在 `fetch_concept()` 中替换概念保存失败日志：

```python
            logger.warning("保存概念 %s 失败: %s", concept_name, exc)
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd backend
pytest tests/test_reported_bugs.py::test_cls_telegraph_fetch_error_logs_warning tests/test_reported_bugs.py::test_irm_checkpoint_write_failure_logs_warning -v
```

预期：2 passed。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/data_source.py backend/app/data_pipeline/fetcher.py backend/tests/test_reported_bugs.py
git commit -m "fix: surface data ingestion failures in warning logs"
```

## 任务 7：durable job partial 结果进入重试

**文件：**
- 修改：`backend/app/data_pipeline/job_handlers.py:42-47`
- 测试：`backend/tests/test_ingestion_job_worker.py`

- [ ] **步骤 1：编写失败的测试**

修改 `backend/tests/test_ingestion_job_worker.py` 中 `test_handler_runs_cninfo_date_job_partial` 的断言为：

```python
    assert result.status == "failed"
    assert result.error == "fetcher returned fail=31"
    assert result.summary["fail"] == 31
```

在同一文件追加 worker 级测试：

```python
def test_worker_retries_partial_fetcher_result(monkeypatch) -> None:
    from app.data_pipeline import job_worker
    from app.data_pipeline.job_handlers import JobExecutionResult

    job = SimpleNamespace(
        id=9,
        attempt_count=1,
        max_attempts=5,
    )
    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(return_value=[job]),
        mark_success=AsyncMock(),
        mark_partial=AsyncMock(),
        mark_failure=AsyncMock(return_value=True),
    )

    async def fake_execute(_job) -> JobExecutionResult:
        return JobExecutionResult(
            status="failed",
            summary={"success": 1800, "fail": 31},
            error="fetcher returned fail=31",
        )

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(
        job_worker.IngestionJobWorker(queue=queue, worker_id="test-worker").run_once(limit=5)
    )

    assert result["failed"] == 1
    queue.mark_failure.assert_awaited_once_with(
        9,
        "test-worker",
        "fetcher returned fail=31",
        1,
        5,
    )
    queue.mark_partial.assert_not_awaited()
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_worker.py::test_handler_runs_cninfo_date_job_partial tests/test_ingestion_job_worker.py::test_worker_retries_partial_fetcher_result -v
```

预期：第一个 FAIL，因为当前 handler 返回 `partial`。

- [ ] **步骤 3：编写最少实现代码**

替换 `backend/app/data_pipeline/job_handlers.py` 中 `_result_from_fetcher_result()`：

```python
def _result_from_fetcher_result(result: dict[str, Any]) -> JobExecutionResult:
    fail = int(result.get("fail", 0) or 0)
    status = JOB_SUCCESS if fail == 0 else JOB_FAILED
    error = None if fail == 0 else f"fetcher returned fail={fail}"
    return JobExecutionResult(status=status, summary=result, error=error)
```

删除未使用的 `JOB_PARTIAL` import。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_worker.py::test_handler_runs_cninfo_date_job_partial tests/test_ingestion_job_worker.py::test_worker_retries_partial_fetcher_result tests/test_ingestion_job_worker.py::test_handler_maps_all_failed_fetcher_result_to_failed -v
```

预期：3 passed。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/job_handlers.py backend/tests/test_ingestion_job_worker.py
git commit -m "fix: retry partial ingestion job results"
```

## 任务 8：巨潮分页最大页数保护

**文件：**
- 修改：`backend/app/data_pipeline/cninfo_client.py:278-320`
- 测试：`backend/tests/test_cninfo_client.py`

- [ ] **步骤 1：编写失败的测试**

在 `backend/tests/test_cninfo_client.py` 追加：

```python
def test_get_announcements_stops_at_max_pages(monkeypatch):
    from app.data_pipeline.cninfo_client import CninfoClient, CninfoClientError

    client = CninfoClient()

    async def endless_query(**kwargs):
        return {
            "total": 0,
            "list": [{"announcementId": f"id-{kwargs['page']}"}],
            "has_more": True,
            "total_pages": 0,
        }

    monkeypatch.setattr(client, "query_announcements", endless_query)

    try:
        asyncio.run(client.get_announcements(ann_date="20260523", max_pages=3))
    except CninfoClientError as exc:
        assert "超过最大分页数 3" in str(exc)
    else:
        raise AssertionError("expected CninfoClientError")
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_cninfo_client.py::test_get_announcements_stops_at_max_pages -v
```

预期：FAIL，报 `unexpected keyword argument 'max_pages'`。

- [ ] **步骤 3：编写最少实现代码**

把 `CninfoClient.get_announcements()` 签名改为：

```python
    async def get_announcements(
        self,
        ann_date: str | None = None,
        ts_code: str | None = None,
        ann_date_end: str | None = None,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        max_pages: int = 500,
    ) -> list[dict[str, Any]]:
```

在 `while True:` 循环开头加入：

```python
            if page > max_pages:
                raise CninfoClientError(
                    f"巨潮 API 分页超过最大分页数 {max_pages}: "
                    f"ann_date={ann_date} ann_date_end={ann_date_end} ts_code={ts_code}"
                )
```

不修改现有调用方，因为默认值覆盖日常路径。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd backend
pytest tests/test_cninfo_client.py::test_get_announcements_stops_at_max_pages -v
```

预期：1 passed。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/cninfo_client.py backend/tests/test_cninfo_client.py
git commit -m "fix: cap cninfo announcement pagination"
```

## 任务 9：集成验证

**文件：**
- 验证：`backend/tests/test_reported_bugs.py`
- 验证：`backend/tests/test_phase31_fetcher.py`
- 验证：`backend/tests/test_phase31_scheduler.py`
- 验证：`backend/tests/test_cninfo_client.py`
- 验证：`backend/tests/test_ingestion_job_worker.py`
- 验证：`backend/tests/test_ingestion_job_queue.py`
- 验证：`backend/tests/test_ingestion_job_producers.py`

- [ ] **步骤 1：运行数据获取层回归测试**

运行：

```bash
cd backend
pytest \
  tests/test_reported_bugs.py \
  tests/test_phase31_fetcher.py \
  tests/test_phase31_scheduler.py \
  tests/test_cninfo_client.py \
  tests/test_ingestion_job_worker.py \
  tests/test_ingestion_job_queue.py \
  tests/test_ingestion_job_producers.py \
  -v
```

预期：全部非 integration 测试通过。若 `@pytest.mark.integration` 测试访问真实 PostgreSQL 失败，改用：

```bash
cd backend
pytest \
  tests/test_reported_bugs.py \
  tests/test_phase31_fetcher.py \
  tests/test_phase31_scheduler.py \
  tests/test_cninfo_client.py \
  tests/test_ingestion_job_worker.py \
  tests/test_ingestion_job_queue.py \
  tests/test_ingestion_job_producers.py \
  -m "not integration" \
  -v
```

预期：全部选中测试通过。

- [ ] **步骤 2：运行语法检查**

运行：

```bash
cd backend
python -m compileall app/data_pipeline tests/test_reported_bugs.py tests/test_phase31_fetcher.py tests/test_phase31_scheduler.py tests/test_cninfo_client.py tests/test_ingestion_job_worker.py
```

预期：命令退出码为 0。

- [ ] **步骤 3：检查变更范围**

运行：

```bash
git diff -- backend/app/data_pipeline backend/tests/test_reported_bugs.py backend/tests/test_phase31_fetcher.py backend/tests/test_phase31_scheduler.py backend/tests/test_cninfo_client.py backend/tests/test_ingestion_job_worker.py
```

预期：diff 只包含本计划列出的修复；没有格式化无关文件。

- [ ] **步骤 4：最终 Commit**

```bash
git add backend/app/data_pipeline backend/tests/test_reported_bugs.py backend/tests/test_phase31_fetcher.py backend/tests/test_phase31_scheduler.py backend/tests/test_cninfo_client.py backend/tests/test_ingestion_job_worker.py
git commit -m "test: verify data access bug fixes"
```

如果前面每个任务都已经独立提交且本步骤没有新增变更，运行：

```bash
git status --short
```

预期：没有与本计划相关的未提交变更。

## 自检

**规格覆盖度：**
- 调度启动 `get_event_loop()` 风险：任务 1 覆盖。
- 限流器线程安全与 akshare async singleton 误导：任务 2 覆盖。
- baostock session 并发互踢：任务 4 覆盖。
- K 线接口失败被统计成空数据：任务 3 和任务 4 覆盖。
- 历史公告 PDF 不触发 KG：任务 5 覆盖新增与修复路径。
- 财联社、IRM checkpoint、股票同步、概念同步日志不可观测：任务 6 覆盖。
- durable job partial 永久停滞：任务 7 覆盖。
- 巨潮分页无上限：任务 8 覆盖。
- 汇总验证：任务 9 覆盖。

**占位符扫描：** 本计划的任务步骤都包含具体文件、测试代码、实现片段、验证命令和预期结果；没有留空步骤。

**类型一致性：**
- `DataSourceClient.get_stock_kline(..., raise_on_error=True)` 在任务 3 定义，任务 4 使用。
- `_on_pdf_download_complete(cninfo_id, file_path, ts_code, title)` 参数顺序与现有实现一致。
- `JobExecutionResult.status` 在任务 7 保持使用现有 `JOB_SUCCESS` / `JOB_FAILED` 常量。
- `CninfoClient.get_announcements(..., max_pages=500)` 新参数有默认值，不破坏现有调用方。
