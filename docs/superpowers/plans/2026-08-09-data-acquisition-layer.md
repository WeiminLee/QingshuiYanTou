# 数据获取层渐进式增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留现有数据表、API 和 Agent 工具契约的前提下，补全 K 线数据正确性、多源 fallback、`daily_basic`、周/月线、调度 scope 和新闻降级。

**Architecture:** 以现有 `DataSourceClient` 为 baostock 兼容适配层，在 `data_pipeline` 内增加轻量 provider registry 与标准记录归一化；`DataFetcher` 负责 fallback 和入库统计，`KlineService` 负责查询与日线聚合，`NewsService` 负责 Tushare/CLS fail-open。provider 失败只影响当前源/当前股票，不中断整批任务。

**Tech Stack:** Python 3.11+, asyncio, pandas, baostock, akshare, SQLAlchemy async engine, PostgreSQL, pytest/pytest-asyncio。

## Global Constraints

- 保留 `daily_data`、`daily_basic`、`index_daily` 表结构和现有 API/Agent 返回字段。
- 默认复权策略保持 `adjustflag="3"`，只有显式启用前复权时才变换 OHLC。
- `daily_basic` 缺失不得导致 `daily_data` 保存失败。
- 只修改本计划列出的文件；不覆盖工作区已有未提交改动。
- 不整体移植参考项目的大型 `DataFetcherManager`，不引入未配置凭证的可选 provider。
- 每个任务先写失败测试，完成后运行该任务的定向测试，再继续依赖任务。

---

## 文件边界

- `backend/app/data_pipeline/data_source.py`：保留 baostock/akshare 原始调用，补充标准 K 线记录和可选源适配入口。
- `backend/app/data_pipeline/providers.py`：新增 provider 协议、标准记录归一化、provider registry 和 fallback 诊断结果。
- `backend/app/data_pipeline/fetcher.py`：使用 registry 获取个股 K 线，写入 `daily_data` 与 best-effort `daily_basic`，返回分项统计。
- `backend/scripts/sync_daily_baostock.py`：修复 `preclose` 字段、复权路径和批量保存语义。
- `backend/app/data_pipeline/services/kline_service.py`：实现日线查询及周/月聚合。
- `backend/app/data_pipeline/backfill_config.py`：复用现有 scope 配置，不改变默认白名单行为。
- `backend/app/data_pipeline/scheduler.py`：把 K 线任务 scope 从硬编码改为配置并增加全市场回填入口。
- `backend/app/data_pipeline/services/news_service.py`：增加 CLS fallback，保持事件幂等。
- `backend/requirements.txt`：只在 provider 实现确实使用新包时声明依赖；已存在的 akshare/baostock 不重复添加。
- `backend/tests/test_data_source_providers.py`：provider 标准化、异常/空结果 fallback。
- `backend/tests/test_phase31_data_source.py`、`backend/tests/test_phase31_fetcher.py`：扩展 K 线源字段、复权和入库统计。
- `backend/tests/test_kline_service.py`：新增日/周/月查询与聚合测试。
- `backend/tests/test_sync_daily_baostock.py`：新增脚本转换与复权测试。
- `backend/tests/test_news_service.py`：新增 Tushare/CLS fallback 和去重测试。
- `backend/tests/test_phase31_scheduler.py`：扩展 scope 传递测试。

---

### Task 1: 建立 K 线标准 provider 协议和 fallback registry

**Files:**
- Create: `backend/app/data_pipeline/providers.py`
- Modify: `backend/app/data_pipeline/data_source.py:360-466`
- Test: `backend/tests/test_data_source_providers.py`

**Interfaces:**
- `StockKlineProvider.fetch_stock_kline(ts_code: str, start_date: str, end_date: str, adjustflag: str = "3") -> list[dict[str, Any]]`
- `KlineProviderResult(records: list[dict], source: str, fallback_used: bool, errors: list[dict])`
- `KlineProviderRegistry.fetch_stock_kline(...) -> KlineProviderResult`
- Standard record keys: `date`, `code`, `open`, `high`, `low`, `close`, `preclose`, `volume`, `amount`, `pctChg`, `tradestatus`.

- [ ] **Step 1: Write failing tests for standardization and fallback**

  Test a fake primary provider raising `RuntimeError` followed by a fake fallback provider returning one row. Assert source is fallback, `fallback_used` is true, and the row has normalized numeric/field names. Add an empty-primary test that also falls through, and an invalid code test that returns a structured error without invoking providers.

- [ ] **Step 2: Run the focused tests to verify failure**

  Run: `cd backend && pytest tests/test_data_source_providers.py -q`
  Expected: collection or assertion failures because `providers.py` and the registry do not exist.

- [ ] **Step 3: Implement the smallest provider layer**

  Define a `Protocol`, immutable result dataclass, `normalize_kline_record()` using `_safe_float`-style conversion, and a registry that invokes providers in configured order. Register a baostock adapter around `DataSourceClient.get_stock_kline(..., raise_on_error=True)`. Register efinance/akshare only when importable and expose construction through an injectable factory so tests never require network access. Treat empty records as a source failure and continue; preserve all provider errors in the result.

- [ ] **Step 4: Run focused tests and existing data-source tests**

  Run: `cd backend && pytest tests/test_data_source_providers.py tests/test_phase31_data_source.py -q`
  Expected: PASS, with existing baostock tests still using mocks.

- [ ] **Step 5: Commit the provider boundary**

  ```bash
  git add backend/app/data_pipeline/providers.py backend/app/data_pipeline/data_source.py backend/tests/test_data_source_providers.py
  git commit -m "feat: add stock kline provider fallback"
  ```

### Task 2: 修复 K 线原始字段、复权和入库统计

**Files:**
- Modify: `backend/scripts/sync_daily_baostock.py:91-190`
- Modify: `backend/app/data_pipeline/fetcher.py:2091-2202`
- Modify: `backend/app/data_pipeline/data_source.py:360-466`
- Test: `backend/tests/test_sync_daily_baostock.py`
- Test: `backend/tests/test_phase31_data_source.py`
- Test: `backend/tests/test_phase31_fetcher.py`

**Interfaces:**
- `_fetch_baostock_raw()` returns rows containing `preclose`.
- `_process_rows()` accepts source pre-close and computes fallback change only when source `pctChg` is absent.
- `_apply_qfq(records, factors, end_date)` returns records with transformed OHLC while leaving volume/amount unchanged.
- `_save_stock_kline()` returns a result that distinguishes daily-data success from basic-data success.

- [ ] **Step 1: Add failing tests**

  Mock baostock rows with `preclose="10"`, `close="11"` and assert the first record has `pre_close=10` and `pct_chg=10`. Add a factor fixture and assert only OHLC changes under explicit qfq. Add a mocked `_save_stock_kline` path where daily data succeeds and basic data is empty; assert the overall result is successful with `basic_success=0` rather than failed.

- [ ] **Step 2: Run tests to confirm current bugs**

  Run: `cd backend && pytest tests/test_sync_daily_baostock.py tests/test_phase31_data_source.py tests/test_phase31_fetcher.py -q`
  Expected: failures showing the script drops `preclose`, qfq is unused, or basic statistics are absent.

- [ ] **Step 3: Implement source field and explicit qfq handling**

  Add `preclose` to the script query fields and row mapping. Use the source pre-close; only use the previous close when the source value is missing and a previous row exists. Add a pure adjustment helper that uses `latest_factor / historical_factor`, skips rows without a valid factor, and is called only when `adjustflag == "2"` or an explicit qfq setting is passed. Keep default `"3"` behavior unchanged.

- [ ] **Step 4: Implement best-effort `daily_basic` upsert**

  Extend the K-line save path with an optional basic record. Upsert only non-empty mapped fields (`close`, turnover, PE/PB, shares and market values) using the existing `(ts_code, trade_date)` unique index. Catch and count basic-write errors separately after the daily-data transaction succeeds. Do not invent values when the provider does not return a field.

- [ ] **Step 5: Run focused and regression tests**

  Run: `cd backend && pytest tests/test_sync_daily_baostock.py tests/test_phase31_data_source.py tests/test_phase31_fetcher.py tests/test_reported_bugs.py -q`
  Expected: PASS; no regression in rate limiter or baostock error accounting.

- [ ] **Step 6: Commit K-line correctness fixes**

  ```bash
  git add backend/scripts/sync_daily_baostock.py backend/app/data_pipeline/data_source.py backend/app/data_pipeline/fetcher.py backend/tests/test_sync_daily_baostock.py backend/tests/test_phase31_data_source.py backend/tests/test_phase31_fetcher.py
  git commit -m "fix: preserve kline fields and basic metrics"
  ```

### Task 3: 将 provider registry 接入 `DataFetcher`

**Files:**
- Modify: `backend/app/data_pipeline/fetcher.py:2157-2380`
- Test: `backend/tests/test_phase31_fetcher.py`

**Interfaces:**
- `DataFetcher.fetch_stock_kline()` consumes `KlineProviderRegistry.fetch_stock_kline()` and returns `total`, `success`, `skipped`, `fail`, `source`, `fallback_used`, `basic_success`, `basic_fail`.

- [ ] **Step 1: Write failing integration-style tests with injected providers**

  Inject a fake registry into `DataFetcher`, return a standard row, mock `_save_stock_kline`, and assert the registry is called with the requested date range and the result exposes source/fallback counters. Add a primary-error/fallback-success case.

- [ ] **Step 2: Run the focused test to see the old call path**

  Run: `cd backend && pytest tests/test_phase31_fetcher.py -k 'stock_kline' -q`
  Expected: failure because `DataFetcher` calls `DataSourceClient` directly and does not expose source diagnostics.

- [ ] **Step 3: Replace the direct call with registry orchestration**

  Add an optional registry dependency to `DataFetcher.__init__` with the production default factory. Preserve the current async thread bridge for blocking providers. Iterate normalized records through the existing save method, aggregate daily/basic counts, and return provider errors in debug logs without raising for a recoverable fallback.

- [ ] **Step 4: Run all K-line tests**

  Run: `cd backend && pytest tests/test_phase31_fetcher.py tests/test_data_source_providers.py tests/test_reported_bugs.py -q`
  Expected: PASS.

- [ ] **Step 5: Commit integration**

  ```bash
  git add backend/app/data_pipeline/fetcher.py backend/tests/test_phase31_fetcher.py
  git commit -m "feat: route stock kline fetches through providers"
  ```

### Task 4: 实现周线/月线查询聚合

**Files:**
- Modify: `backend/app/data_pipeline/services/kline_service.py:19-108`
- Test: `backend/tests/test_kline_service.py`

**Interfaces:**
- `KlineService.get_stock_kline(..., frequency="d")` retains existing daily output.
- `frequency="w"` groups by ISO trading week; `frequency="m"` groups by `YYYY-MM`.
- Aggregated records preserve `ts_code`, `trade_date`, OHLCV, amount, pct_chg, turnover_rate.

- [ ] **Step 1: Write failing aggregation tests**

  Mock three daily rows spanning two weeks and two months. Assert weekly/monthly open is first open, high is max, low is min, close is last close, volume/amount are sums, and pct change uses the first period pre-close/first open context. Assert daily queries remain unchanged and invalid frequency returns `[]` with a warning.

- [ ] **Step 2: Run the focused tests**

  Run: `cd backend && pytest tests/test_kline_service.py -q`
  Expected: failures because `frequency` is currently ignored.

- [ ] **Step 3: Implement a pure aggregation helper**

  Query daily rows once, validate frequency in `{"d", "w", "m"}`, group Python dictionaries using parsed dates, and emit the documented fields. Keep SQL parameterization and existing exception behavior. Do not change index K-line behavior in this task.

- [ ] **Step 4: Run K-line service and tool tests**

  Run: `cd backend && pytest tests/test_kline_service.py tests/test_tools_functional.py -k 'kline' -q`
  Expected: PASS.

- [ ] **Step 5: Commit aggregation**

  ```bash
  git add backend/app/data_pipeline/services/kline_service.py backend/tests/test_kline_service.py
  git commit -m "feat: aggregate stock kline by week and month"
  ```

### Task 5: 配置化 K 线调度并补新闻 fallback

**Files:**
- Modify: `backend/app/data_pipeline/scheduler.py:457-485`
- Modify: `backend/app/data_pipeline/services/news_service.py:45-116`
- Test: `backend/tests/test_phase31_scheduler.py`
- Test: `backend/tests/test_news_service.py`

**Interfaces:**
- `_run_kline_job()` passes `load_backfill_settings().scope` to `sync_daily()`.
- `NewsService.fetch_and_save()` tries Tushare first and CLS only on exception or empty result; both map to the existing event schema.

- [ ] **Step 1: Write failing tests**

  Set `BACKFILL_SCOPE=all`, mock `sync_daily`, and assert it receives `scope="all"`. Mock Tushare exception/empty dataframe and `DataSourceClient.get_cls_telegraph()` records; assert fallback records are inserted with stable IDs. Add duplicate CLS rows and assert one event insert.

- [ ] **Step 2: Run focused tests**

  Run: `cd backend && pytest tests/test_phase31_scheduler.py tests/test_news_service.py -q`
  Expected: scheduler assertion shows hard-coded `tech_mvp`, and news fallback test fails because CLS is not called.

- [ ] **Step 3: Implement scope and fallback**

  Load settings once per job and pass the configured scope. In `NewsService`, keep Tushare response handling unchanged for success; on exception or empty result call `DataSourceClient.get_cls_telegraph()`, map `标题/内容/发布日期/发布时间` to the existing fields, and reuse `stable_event_id` plus `ON CONFLICT DO NOTHING`.

- [ ] **Step 4: Run scheduler/readiness/news regressions**

  Run: `cd backend && pytest tests/test_phase31_scheduler.py tests/test_news_service.py tests/test_readiness_service.py tests/test_readiness_api.py -q`
  Expected: PASS.

- [ ] **Step 5: Commit operational fallbacks**

  ```bash
  git add backend/app/data_pipeline/scheduler.py backend/app/data_pipeline/services/news_service.py backend/tests/test_phase31_scheduler.py backend/tests/test_news_service.py
  git commit -m "feat: configure kline scope and add news fallback"
  ```

### Task 6: Full verification and integration review

**Files:**
- Modify only files required by failing tests found in this task.
- Test: all listed data-pipeline tests plus the backend suite.

- [ ] **Step 1: Run focused data-layer suite**

  Run: `cd backend && pytest tests/test_data_source_providers.py tests/test_sync_daily_baostock.py tests/test_phase31_data_source.py tests/test_phase31_fetcher.py tests/test_kline_service.py tests/test_news_service.py tests/test_phase31_scheduler.py -q`
  Expected: PASS.

- [ ] **Step 2: Run the complete backend test suite**

  Run: `cd backend && pytest -q`
  Expected: PASS, or only pre-existing failures documented with exact test names and reasons.

- [ ] **Step 3: Check formatting, imports, and diff scope**

  Run: `cd backend && python -m compileall -q app scripts && git diff --check`
  Expected: exit code 0; `git status --short` shows only intended implementation files plus pre-existing user changes.

- [ ] **Step 4: Review runtime safety**

  Confirm provider imports are optional/lazy, no network calls occur at import time, fallback errors include source names, and default `BACKFILL_SCOPE=tech_mvp` remains unchanged.

- [ ] **Step 5: Close the integration review without touching unrelated work**

  The implementation commits from Tasks 1-5 are the integration units. Do not create a broad cleanup commit. Before handoff, run `git diff --name-only HEAD~5..HEAD` and verify every listed path belongs to this plan; leave all pre-existing user changes unstaged.
