# Data Access Layer Code Review

**Reviewed:** 2026-05-15T00:00:00Z
**Depth:** deep
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Reviewed the data access layer in `backend/app/data_pipeline/` including fetcher.py, data_source.py, scheduler.py, monitor.py, file_storage.py, rate_limiter.py, and dingtalk.py. Found **4 CRITICAL issues**, **8 WARNING issues**, and **6 INFO items**. The code uses parameterized SQL queries (good) but has race conditions, silent exception swallowing, unsafe async patterns, and architectural issues.

---

## Critical Issues

### CR-01: Race Condition in Singleton Pattern

**File:** `rate_limiter.py:97-100`
**Severity:** CRITICAL
**Issue:** The singleton initialization is not thread-safe. Multiple threads can simultaneously pass the `None` check and create duplicate limiters.

```python
def get_akshare_limiter() -> RateLimiter:
    global _akshare_limiter
    if _akshare_limiter is None:  # Race: multiple threads can pass here
        _akshare_limiter = RateLimiter(...)  # Duplicate instances created
    return _akshare_limiter
```

**Impact:** In multi-threaded contexts, multiple `RateLimiter` instances may be created, defeating the rate limiting purpose. Both `_akshare_limiter` and `_cninfo_pdf_limiter` are affected.

**Recommendation:**
```python
def get_akshare_limiter() -> RateLimiter:
    global _akshare_limiter
    if _akshare_limiter is None:
        with threading.Lock():  # Double-checked locking pattern
            if _akshare_limiter is None:
                _akshare_limiter = RateLimiter(max_requests=1, window_seconds=1.0, name="akshare")
    return _akshare_limiter
```

---

### CR-02: Deprecated `get_event_loop()` Pattern

**File:** `scheduler.py:356`
**Severity:** CRITICAL
**Issue:** Uses deprecated `asyncio.get_event_loop()` which raises `DeprecationWarning` and `RuntimeError` in Python 3.10+ when no running event loop exists.

```python
def _fire_all_once(self) -> None:
    loop = asyncio.get_event_loop()  # CRITICAL: deprecated and unsafe
```

**Impact:** On Python 3.10+, this will raise `RuntimeError: There is no current event loop in the main thread` when called from a non-async context, causing the scheduled tasks to fail silently.

**Recommendation:**
```python
def _fire_all_once(self) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    # Use loop to create tasks...
```

Or better: make `_fire_all_once` an async method and use `asyncio.get_running_loop()`.

---

### CR-03: Silent Exception Swallowing Without Logging

**File:** `data_source.py:244-245` (get_cls_telegraph)
**File:** `data_source.py:168-170` (get_reports)
**File:** `fetcher.py:847` (_save_concept_limit)
**Severity:** CRITICAL

**Issue:** Multiple locations catch exceptions and return empty results without any logging, making debugging impossible.

```python
# data_source.py:244-245
except Exception:
    return []  # Silent failure - no logging
```

```python
# fetcher.py:847
except Exception as exc:
    fail += 1
    logger.debug("保存概念 %s 失败: %s", concept_name, exc)  # Only debug level
```

**Impact:** When data fetching fails, operators have no visibility into the failure. Using `debug` level for failures means production logs won't show them.

**Recommendation:** Log at WARNING or ERROR level:
```python
logger.warning("获取财联社电报失败: %s", e)
return []
```

---

### CR-04: Blocking Synchronous HTTP in Async Context

**File:** `dingtalk.py:128`
**Severity:** CRITICAL
**Issue:** Uses synchronous `httpx.Client` in `_send()` which is called from async functions via `notify_*()` methods without proper thread isolation.

```python
def _send(payload: dict) -> bool:
    try:
        webhook_url = _get_webhook_url()
        with httpx.Client(timeout=10) as client:  # Blocking call
            response = client.post(...)
```

**Impact:** While `_send` itself is synchronous (called from sync `notify_*` functions), if these are ever called from async contexts without `asyncio.to_thread()`, they will block the event loop.

**Recommendation:** Either:
1. Keep synchronous and document that it must be wrapped with `asyncio.to_thread()` when called from async code
2. Or convert to async using `httpx.AsyncClient`

---

## Warnings

### WR-01: Fire-and-Forget Async Calls in Scheduler

**File:** `scheduler.py:94, 128, 158, 191, 257`
**Severity:** WARNING
**Issue:** `notify_*` functions are called without `await`, meaning they execute synchronously and any exceptions are silently swallowed.

```python
notify_task_start("研报同步")  # Not awaited
notify_task_success(...)       # Not awaited
notify_task_failed(...)        # Not awaited
```

**Impact:** If DingTalk notification fails, the exception is never raised or logged at the caller level. The notification failure is invisible to the monitoring system.

**Recommendation:** Either await these calls or wrap them with proper error handling:
```python
try:
    notify_task_start("研报同步")
except Exception as e:
    logger.warning("钉钉通知失败: %s", e)
```

---

### WR-02: MongoDB Checkpoint Timezone Inconsistency

**File:** `fetcher.py:384, 407-411`
**Severity:** WARNING
**Issue:** The checkpoint stores `datetime.now(timezone.utc)` but compares against `datetime.now()` (naive, local time) in filtering logic.

```python
# Stores with UTC timezone
now = datetime.now(timezone.utc)
update["last_success_at"] = now

# But filtering uses:
cutoff = datetime.now(timezone.utc) - timedelta(hours=IRM_CHECKPOINT_WINDOW_HOURS)
cursor = db[IRM_CHECKPOINT_COLLECTION].find({
    "last_success_at": {"$gt": cutoff},  # UTC vs local comparison
```

**Impact:** If the server timezone differs from UTC, the checkpoint window calculation will be off by the timezone offset, potentially causing incorrect filtering.

**Recommendation:** Ensure consistent timezone handling throughout:
```python
# Use UTC consistently
now = datetime.now(timezone.utc)
cutoff = datetime.now(timezone.utc) - timedelta(hours=IRM_CHECKPOINT_WINDOW_HOURS)
```

---

### WR-03: Missing ON CONFLICT Handler in _save_concept_limit

**File:** `fetcher.py:875-885`
**Severity:** WARNING
**Issue:** `_save_concept_limit` has no try/except block. Any database error will propagate up and potentially crash the batch job.

```python
async with engine.begin() as conn:
    await conn.execute(
        text(sql),
        {...}
    )  # No exception handling
```

**Impact:** A single failing record can cause the entire concept sync batch to fail.

**Recommendation:** Add error handling:
```python
try:
    async with engine.begin() as conn:
        await conn.execute(text(sql), {...})
except Exception as exc:
    logger.warning("保存概念失败 [%s]: %s", concept_name, exc)
    raise  # Or increment fail counter
```

---

### WR-04: N+1 Database Pattern in sync_stocks

**File:** `fetcher.py:757-776`
**Severity:** WARNING
**Issue:** Uses individual INSERT statements in a loop instead of batch operations.

```python
for stock in stocks:
    # Individual INSERT per stock
    async with engine.begin() as conn:
        await conn.execute(text(sql), {...})
```

**Impact:** For ~5000 stocks, this creates 5000 separate database round-trips. Performance degrades significantly with large datasets.

**Recommendation:** Use `executemany()` or batch inserts:
```python
values = [{"ts_code": s["ts_code"], ...} for s in stocks if s.get("ts_code")]
if values:
    async with engine.begin() as conn:
        await conn.execute(text(sql), values)
```

---

### WR-05: Missing Index on IRM Checkpoint Collection

**File:** `fetcher.py:368-376`
**Severity:** WARNING
**Issue:** `_ensure_irm_checkpoint_index` only creates indexes if they don't exist, but uses `create_index` which is not idempotent for async MongoDB drivers.

```python
await col.create_index("ts_code", unique=True)  # Creates if not exists
await col.create_index("last_success_at")       # Creates if not exists
```

**Impact:** In async MongoDB, `create_index` is idempotent but may cause warning logs. More importantly, if the async iteration cursor is not properly awaited, it could lead to issues.

**Recommendation:** Use `create_indexes` for batch creation or handle async properly:
```python
await col.create_indexes([
    pymongo.IndexModel([("ts_code", ASCENDING)], unique=True),
    pymongo.IndexModel([("last_success_at", ASCENDING)])
])
```

---

### WR-06: Hardcoded Referer Header Spoofing

**File:** `file_storage.py:26`
**Severity:** WARNING
**Issue:** Hardcoded Referer header claims requests come from cninfo.com.cn, which could be problematic.

```python
HTTP_HEADERS = {
    "Referer": "http://www.cninfo.com.cn/",  # Claiming to be from another site
    ...
}
```

**Impact:** This could be interpreted as referer spoofing. Additionally, if cninfo.com.cn changes their anti-bot measures, these headers may stop working.

**Recommendation:** Use legitimate headers or remove the Referer if not strictly necessary. Document why this specific header is required.

---

### WR-07: Missing Storage Path Validation

**File:** `file_storage.py:56-64, 94-96`
**Severity:** WARNING
**Issue:** No validation that constructed paths remain within expected directories, risking path traversal attacks.

```python
def _get_notice_path(self, ts_code: str, pub_date: str, filename: str) -> Path:
    storage_dir = self.notices_dir / ts_code / year_month
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / filename  # No validation that filename is safe
```

**Impact:** If `filename` contains `../`, files could be written outside the intended storage directory.

**Recommendation:** Validate and sanitize inputs:
```python
def _sanitize_filename(self, filename: str) -> str:
    # Remove path separators and null bytes
    return filename.replace("/", "_").replace("\\", "_").replace("\0", "")
```

---

### WR-08: Data Loss Risk - fetch_reports Silent Failure

**File:** `fetcher.py:241-245`
**Severity:** WARNING
**Issue:** When `_save_report` catches `IntegrityError` it returns `None`, but the calling code treats this as "skipped" rather than an actual duplicate or error condition.

```python
except IntegrityError:
    return None  # Treated as "skipped" by caller
except Exception as exc:
    logger.warning("保存研报失败 [%s]: %s", ann_id, exc)
    return False  # Failure
```

**Impact:** If a unique constraint violation occurs due to a race condition, it's silently counted as "skipped" rather than logged as an issue.

**Recommendation:** Log IntegrityError cases explicitly:
```python
except IntegrityError:
    logger.debug("研报已存在 [%s]", ann_id)
    return None
```

---

## Info Items

### IN-01: Missing config.py in data_pipeline/

**File:** `backend/app/data_pipeline/config.py`
**Severity:** INFO
**Issue:** The config.py file does not exist in the data_pipeline directory. The dingtalk.py module tries to import from `app.data_pipeline.config` but should use `app.config` instead.

```python
# dingtalk.py imports from wrong location:
from app.data_pipeline.dingtalk import notify_alert  # Wrong
# Should be from app.dingtalk import notify_alert
```

**Impact:** Import errors or fallback to `app.config.settings` in monitor.py works but is fragile.

**Recommendation:** Use consistent import paths: `from app.config import settings`.

---

### IN-02: Dead Code Reference

**File:** `fetcher.py:741`
**Severity:** INFO
**Issue:** Comment references a removed instance method that no longer exists.

```python
# Phase 31 CR-01: instance method removed — module-level fetch_concept() called directly
```

**Impact:** Code comment documents historical change but the comment itself is dead code.

**Recommendation:** Remove the comment or replace with actual documentation of the current architecture.

---

### IN-03: Missing dingtalk_secret in Settings

**File:** `app/config.py`
**Severity:** INFO
**Issue:** The `Settings` class defines `dingtalk_webhook_url` but not `dingtalk_secret`, yet `dingtalk.py` tries to access `settings.dingtalk_secret`.

```python
# app/config.py
dingtalk_webhook_url: str = ""

# dingtalk.py
DINGTALK_SECRET = getattr(settings, 'dingtalk_secret', '') or ''  # Missing from Settings!
```

**Impact:** Falls back to empty string, disabling signature functionality even if configured.

**Recommendation:** Add `dingtalk_secret: str = ""` to Settings class.

---

### IN-04: Magic Numbers Without Constants

**File:** `scheduler.py:42-48`
**Severity:** INFO
**Issue:** Magic numbers used for cron schedule times without named constants.

```python
REPORT_FETCH_HOUR = 3
KLINE_FETCH_HOUR = 17
KLINE_FETCH_MINUTE = 30
IRM_HOUR = 22
```

**Impact:** Code is readable but these should be documented or moved to a configuration file.

---

### IN-05: Debug-Level Logging for Failures

**File:** `fetcher.py:776`
**Severity:** INFO
**Issue:** Stock sync failures use debug-level logging, which is typically disabled in production.

```python
logger.debug("股票同步失败 %s: %s", ts_code, exc)
```

**Impact:** Production issues will be invisible in logs.

**Recommendation:** Use WARNING level for non-critical operational failures:
```python
logger.warning("股票同步失败 %s: %s", ts_code, exc)
```

---

### IN-06: Baostock Login Without Error Handling

**File:** `data_source.py:116-120`
**Severity:** INFO
**Issue:** `_bs_login()` calls `bs.login()` without error handling. If login fails, all subsequent operations will fail.

```python
def _bs_login(self):
    if not self._bs_logged_in:
        bs.login()  # No try/except
        self._bs_logged_in = True
```

**Impact:** If baostock service is temporarily unavailable, login silently fails and subsequent queries return empty results.

**Recommendation:** Add error handling and retry logic:
```python
def _bs_login(self):
    if not self._bs_logged_in:
        try:
            result = bs.login()
            if result.error_code == "0":
                self._bs_logged_in = True
            else:
                logger.error("baostock login failed: %s", result.error_msg)
        except Exception as e:
            logger.error("baostock login exception: %s", e)
```

---

## Findings Summary

| Severity | Count |
|----------|-------|
| Critical | 4 |
| Warning | 8 |
| Info | 6 |
| **Total** | **18** |

### Critical Issues by File

| File | Count | Issues |
|------|-------|--------|
| rate_limiter.py | 1 | Race condition in singleton |
| scheduler.py | 1 | Deprecated get_event_loop() |
| data_source.py | 1 | Silent exception swallowing |
| dingtalk.py | 1 | Blocking sync HTTP |
| fetcher.py | 1 | Silent exception swallowing |

### Top Recommendations (Priority Order)

1. **Fix race condition** in rate_limiter.py singleton pattern
2. **Replace `get_event_loop()`** with `get_running_loop()` in scheduler.py
3. **Add logging** at WARNING level for all exception handlers
4. **Document async/sync boundaries** or convert dingtalk.py to async
5. **Add input validation** for file storage paths
6. **Implement batch inserts** for stock sync performance

---

_Reviewed: 2026-05-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
