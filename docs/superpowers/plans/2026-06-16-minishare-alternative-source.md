# minishare 备选数据通道 Implementation Plan

> **Status:** ✅ Implementation complete — all tasks committed to `main`

**Goal:** 为研报和互动易数据新增 minishare 备选数据获取通道，不删除现有 akshare/cninfo 通道。

**Architecture:** 新建 `minishare_client.py` 数据源模块，复用现有 `DataFetcher` 的入库逻辑，在 API 层暴露独立 endpoint。调度器按需调用或作为故障转移。历史批量同步支持断点续跑。

**Tech Stack:** minishare SDK (`pip install minishare --extra-index-url https://minidoc.pages.dev/simple/ -U`), pandas, asyncio, IngestionProgressTracker

---

## Implementation Summary (2026-06-16)

| Task | Description | Status |
|------|-------------|--------|
| 1 | minishare tokens in config.py | ✅ |
| 2 | minishare_client.py data source wrapper | ✅ |
| 3 | DataFetcher fetch_minishare_* methods | ✅ |
| 4 | API endpoints for daily sync | ✅ |
| 5 | .env.example minishare config docs | ✅ |
| 6 | minishare_client iter_*_date_range helpers | ✅ |
| 7 | IngestionProgressTracker checkpoint tracking | ✅ |
| 8 | FileStorage download_report_external | ✅ |
| 9 | DataFetcher history batch methods | ✅ |
| 10 | API endpoints for history batch sync | ✅ |
| 11 | config.py comments clarification | ✅ |

## API Endpoints

```
POST /api/v1/sync/minishare/reports         # 按日期或股票获取研报
POST /api/v1/sync/minishare/irm            # 按日期获取互动易
POST /api/v1/sync/minishare/reports/history # 批量回填研报（断点续跑）
POST /api/v1/sync/minishare/irm/history    # 批量回填互动易（断点续跑）
GET  /api/v1/sync/minishare/progress       # 查询断点进度
```

## Environment Variables

```bash
# 研报授权码
MINISHARE_RESEARCH_TOKEN=frKxy02rbm3MuEr6B8iLtJp7jOkx4TFr45iwEt1f6c6l51cqqBbCnZO058e3e5c9
# 互动易授权码
MINISHARE_IRM_TOKEN=frN7x674UW3OkMi3cp2r1Dm1Aq3C0ha7wDvNUU76P6uCQyemCV6uVBaZd251f0b7
# 外部数据存储路径
MINISHARE_DATA_ROOT=/home/lwm/qingshui_data
```

---

## File Structure

- Create: `app/data_pipeline/minishare_client.py` — minishare API 封装（`DataSourceClientMinishare`）
- Create: `app/data_pipeline/progress_tracker.py` — `IngestionProgressTracker` 断点续跑
- Modify: `app/config.py` — 新增 `MINISHARE_*` 配置项 + `minishare_data_root`
- Modify: `app/data_pipeline/fetcher.py` — 新增 `fetch_minishare_reports()` / `fetch_minishare_irm()` / `fetch_*_history()` 方法
- Modify: `app/data_pipeline/storage.py` — 新增 `download_report_external()` 方法
- Modify: `app/data_pipeline/api/data_sync.py` — 新增 minishare API endpoints

---

## Task 1: 配置项 — 添加 minishare tokens 到 config.py

**Files:**
- Modify: `app/config.py:93-95` (在 `dingtalk_webhook_url` 之后添加)

- [ ] **Step 1: 添加配置字段**

```python
    # minishare（备选数据源）
    minishare_research_token: str = ""   # 研报授权码
    minishare_irm_token: str = ""       # 互动易（董秘问答）授权码
```

- [ ] **Step 2: 运行验证**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && python -c "from app.config import settings; print(settings.minishare_research_token, settings.minishare_irm_token)"`
Expected: 输出空字符串（未配置环境变量，正常）

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "feat(config): add minishare tokens"
```

---

## Task 2: 新建 minishare_client.py — minishare 数据源封装

**Files:**
- Create: `app/data_pipeline/minishare_client.py`

- [ ] **Step 1: 写文件**

```python
"""
DataSourceClientMinishare — minishare 备选数据源

数据源：
- 研报: pro.research_report(trade_date=) / pro.research_report(ts_code=, start_date=, end_date=)
- 互动易: pro.irm_qa_sh(trade_date=) / pro.irm_qa_sz(trade_date=)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import minishare as ms
import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)


def _is_null(val) -> bool:
    """判断值是否为空（None / pandas NaN / 字符串 nan/nat/none/null）"""
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(val, str):
        return val.strip().lower() in ("", "nan", "nat", "none", "null")
    return False


def _safe_str(val) -> str:
    """安全转字符串，空值转空字符串"""
    if _is_null(val):
        return ""
    if hasattr(val, "date") and hasattr(val, "hour"):
        try:
            return val.strftime("%Y%m%d")
        except Exception:
            return ""
    return str(val)


def _safe_str_full(val) -> str:
    """安全转完整字符串（保留时间），空值转空字符串"""
    if _is_null(val):
        return ""
    if hasattr(val, "date") and hasattr(val, "hour"):
        try:
            return val.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""
    return str(val)


def _normalize_ts_code(code: str) -> str:
    """标准化股票代码格式"""
    if not code:
        return ""
    c = code.strip()
    if "." not in c:
        return f"{c}.SH" if c.startswith("6") else f"{c}.SZ"
    prefix, num = c.split(".", 1)
    if prefix.lower() in ("sh", "ss"):
        return f"{num}.SH"
    if prefix.lower() in ("sz",):
        return f"{num}.SZ"
    return c.upper()


class DataSourceClientMinishare:
    """minishare 备选数据源客户端"""

    def __init__(self) -> None:
        research_token = settings.minishare_research_token
        irm_token = settings.minishare_irm_token

        if not research_token:
            logger.warning("MINISHARE_RESEARCH_TOKEN 未配置，研报数据源不可用")
            self._research_api = None
        else:
            self._research_api = ms.pro_api(research_token)

        if not irm_token:
            logger.warning("MINISHARE_IRM_TOKEN 未配置，互动易数据源不可用")
            self._irm_api = None
        else:
            self._irm_api = ms.pro_api(irm_token)

    @property
    def research_available(self) -> bool:
        return self._research_api is not None

    @property
    def irm_available(self) -> bool:
        return self._irm_api is not None

    def get_reports(
        self,
        trade_date: Optional[str] = None,
        ts_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """获取券商研报数据（minishare）。

        Args:
            trade_date: 按研报日期 YYYYMMDD，如 '20260516'
            ts_code: 按股票代码，如 '600519.SH'
            start_date: 按股票代码时的起始日期 YYYYMMDD
            end_date: 按股票代码时的结束日期 YYYYMMDD
            limit: 最大返回条数
        """
        if not self.research_available:
            logger.warning("研报数据源未配置 token")
            return []

        try:
            if trade_date:
                df = self._research_api.research_report(trade_date=trade_date)
            elif ts_code:
                df = self._research_api.research_report(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                logger.warning("get_reports 需要 trade_date 或 ts_code 参数")
                return []

            if df is None or len(df) == 0:
                logger.info("minishare 研报数据为空")
                return []

            records = []
            for _, row in df.iterrows():
                pub_date = _safe_str(row.get("trade_date") or row.get("日期"))
                if not pub_date:
                    continue
                ts_code_val = _normalize_ts_code(str(row.get("ts_code") or row.get("股票代码") or ""))
                records.append({
                    "trade_date": pub_date,
                    "ts_code": ts_code_val,
                    "name": _safe_str(row.get("name") or row.get("股票简称")),
                    "title": _safe_str(row.get("title") or row.get("报告名称")),
                    "inst_csname": _safe_str(row.get("inst_csname") or row.get("机构")),
                    "author": _safe_str(row.get("author") or row.get("作者")),
                    "org_code": "",
                    "url": _safe_str(row.get("url") or row.get("链接")),
                    "file_name": "",
                })

            logger.info(f"minishare 获取研报数据: {len(records)} 条")
            return records[:limit]
        except Exception as e:
            logger.error(f"minishare 获取研报数据失败: {e}")
            return []

    def get_irm(self, trade_date: str) -> list[dict[str, Any]]:
        """获取互动易 Q&A（minishare，深交所 + 上交所）。

        Args:
            trade_date: 日期 YYYYMMDD，如 '20260512'
        """
        if not self.irm_available:
            logger.warning("互动易数据源未配置 token")
            return []

        records: list[dict[str, Any]] = []

        # 上证
        try:
            df_sh = self._irm_api.irm_qa_sh(trade_date=trade_date)
            if df_sh is not None and len(df_sh) > 0:
                for _, row in df_sh.iterrows():
                    answer = _safe_str(row.get("answer") or row.get("回答"))
                    if not answer:
                        continue
                    records.append({
                        "stock_code": _safe_str(row.get("stock_code") or row.get("股票代码")),
                        "stock_name": _safe_str(row.get("stock_name") or row.get("公司简称")),
                        "question": _safe_str(row.get("question") or row.get("问题")),
                        "answer": answer,
                        "question_time": _safe_str_full(row.get("question_time") or row.get("提问时间")),
                        "answer_time": _safe_str_full(row.get("answer_time") or row.get("回答时间")),
                        "exchange": "SH",
                    })
                logger.info(f"minishare 上证互动易: {len(df_sh)} 条")
        except Exception as e:
            logger.warning(f"minishare 上证互动易失败: {e}")

        # 深证
        try:
            df_sz = self._irm_api.irm_qa_sz(trade_date=trade_date)
            if df_sz is not None and len(df_sz) > 0:
                for _, row in df_sz.iterrows():
                    answer = _safe_str(row.get("answer") or row.get("回答内容"))
                    if not answer:
                        continue
                    records.append({
                        "stock_code": _safe_str(row.get("stock_code") or row.get("股票代码")),
                        "stock_name": _safe_str(row.get("stock_name") or row.get("公司简称")),
                        "question": _safe_str(row.get("question") or row.get("问题")),
                        "answer": answer,
                        "question_time": _safe_str_full(row.get("question_time") or row.get("提问时间")),
                        "answer_time": _safe_str_full(row.get("answer_time") or row.get("更新时间")),
                        "exchange": "SZ",
                    })
                logger.info(f"minishare 深证互动易: {len(df_sz)} 条")
        except Exception as e:
            logger.warning(f"minishare 深证互动易失败: {e}")

        return records
```

- [ ] **Step 2: 运行验证**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && python -c "from app.data_pipeline.minishare_client import DataSourceClientMinishare; c = DataSourceClientMinishare(); print('research:', c.research_available, 'irm:', c.irm_available)"`
Expected: `research: False irm: False`（未配置 token，正常）

- [ ] **Step 3: Commit**

```bash
git add app/data_pipeline/minishare_client.py
git commit -m "feat: add minishare data source client"
```

---

## Task 3: DataFetcher — 新增 minishare fetch 方法

**Files:**
- Modify: `app/data_pipeline/fetcher.py` — 在 `DataFetcher` 类末尾（`_save_report` 方法附近）添加两个新方法

- [ ] **Step 1: 添加 minishare_client 导入**

在 fetcher.py 文件顶部（其他导入附近），找到：
```python
from app.data_pipeline.cninfo_client import CninfoClient
from app.data_pipeline.data_source import DataSourceClient
```

在之后添加：
```python
from app.data_pipeline.minishare_client import DataSourceClientMinishare
```

- [ ] **Step 2: 在 DataFetcher.__init__ 添加 minishare_client 实例化**

在 `__init__` 方法中添加：
```python
        self.minishare_client = DataSourceClientMinishare()
```

- [ ] **Step 3: 添加 fetch_minishare_reports 方法**

在 `DataFetcher` 类中添加（在 `# ---------- 研报 ----------` 区块之后，`fetch_reports` 之后）：

```python
    async def fetch_minishare_reports(
        self,
        trade_date: str | None = None,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        """从 minishare 获取研报并入库（备选通道）。"""
        task_id = generate_task_id()
        set_task_id(task_id)

        if trade_date is None:
            trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        if not self.minishare_client.research_available:
            logger.warning("minishare 研报 token 未配置，跳过")
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        logger.info("开始从 minishare 获取研报: %s", trade_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"开始从 minishare 获取研报: {trade_date}",
            task_id=task_id,
            trade_date=trade_date,
        )

        reports = await asyncio.to_thread(
            self.minishare_client.get_reports,
            trade_date=trade_date,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        # 复用 fetch_reports 的 EXISTS 预查询 + 入库逻辑
        candidates: list[dict[str, Any]] = []
        for report in reports:
            title = str(report.get("title") or "")
            inst_csname = str(report.get("inst_csname") or "")
            author = str(report.get("author") or "")
            url = str(report.get("url") or "")
            ts_code_val = _norm_ts_code(report.get("ts_code"))

            ann_id: str | None = None
            if url:
                try:
                    pdf_part = url.split("/")[-1].split("?")[0]
                    if pdf_part:
                        ann_id = f"ms_report_{pdf_part}"
                except Exception:
                    ann_id = None
            if not ann_id:
                ann_id = _stable_id("ms_report", trade_date, title, inst_csname)

            candidates.append({
                "ann_id": ann_id,
                "ts_code": ts_code_val,
                "title": title,
                "inst_csname": inst_csname,
                "author": author,
                "url": url,
            })

        candidate_ann_ids = [c["ann_id"] for c in candidates]
        existing: set[str] = set()
        if candidate_ann_ids:
            try:
                async with engine.connect() as conn:
                    rows = await conn.execute(
                        text("SELECT file_name FROM research_report_meta WHERE file_name = ANY(:ids)"),
                        {"ids": candidate_ann_ids},
                    )
                    existing = {r[0] for r in rows.fetchall()}
            except Exception as exc:
                logger.warning("研报 EXISTS 预查询失败: %s", exc)

        total = len(candidates)
        success = skipped = fail = 0
        for c in candidates:
            if c["ann_id"] in existing:
                skipped += 1
                continue

            saved = await self._save_report(
                ann_id=c["ann_id"],
                ts_code=c["ts_code"],
                title=c["title"],
                trade_date=trade_date,
                inst_csname=c["inst_csname"],
                author=c["author"],
                source_name="minishare",
            )
            if saved is True:
                success += 1
            elif saved is None:
                skipped += 1
            else:
                fail += 1

        logger.info(
            "minishare 研报获取完成: 总 %d，新增 %d，跳过 %d，失败 %d",
            total, success, skipped, fail,
        )
        return {"total": total, "success": success, "skipped": skipped, "fail": fail, "source": "minishare"}
```

- [ ] **Step 4: 修改 _save_report 支持 source_name 参数**

找到 `_save_report` 方法签名：
```python
    async def _save_report(
        self,
        ann_id: str,
        ts_code: str,
        title: str,
        trade_date: str,
        inst_csname: str,
        author: str,
    ) -> bool | None:
```

改为：
```python
    async def _save_report(
        self,
        ann_id: str,
        ts_code: str,
        title: str,
        trade_date: str,
        inst_csname: str,
        author: str,
        source_name: str = "akshare",
    ) -> bool | None:
```

找到 SQL INSERT 中的 `source_name` 字段：
```python
            source_name=:source_name,
```
已存在，无需修改（`source_name` 来自参数）。

- [ ] **Step 5: 添加 fetch_minishare_irm 方法**

在 `DataFetcher` 类中添加（在 `# ---------- 互动易 ----------` 区块之后，`fetch_irm` 之后）：

```python
    async def fetch_minishare_irm(
        self,
        trade_date: str | None = None,
    ) -> dict[str, int]:
        """从 minishare 获取互动易 Q&A 并入库（备选通道）。"""
        task_id = generate_task_id()
        set_task_id(task_id)

        if trade_date is None:
            trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        if not self.minishare_client.irm_available:
            logger.warning("minishare 互动易 token 未配置，跳过")
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        logger.info("开始从 minishare 获取互动易: %s", trade_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"开始从 minishare 获取互动易: {trade_date}",
            task_id=task_id,
            trade_date=trade_date,
        )

        records = await asyncio.to_thread(
            self.minishare_client.get_irm,
            trade_date=trade_date,
        )

        if not records:
            logger.info("minishare 互动易数据为空")
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        success = skipped = fail = 0
        for rec in records:
            # 复用 _save_irm_record 的逻辑（ts_code 从 stock_code 推断）
            ts_code = _norm_ts_code(rec.get("stock_code") or "")
            if ts_code and "." not in ts_code:
                # 裸数字股票代码标准化
                ts_code = _normalize_ts_code(ts_code)
            ok = await self._save_irm_record(ts_code or "UNKNOWN", rec)
            if ok is True:
                success += 1
            elif ok is None:
                skipped += 1
            else:
                fail += 1

        logger.info(
            "minishare 互动易获取完成: 总 %d，新增 %d，跳过 %d，失败 %d",
            len(records), success, skipped, fail,
        )
        return {"total": len(records), "success": success, "skipped": skipped, "fail": fail, "source": "minishare"}
```

- [ ] **Step 6: 添加 _normalize_ts_code 辅助函数**

在 fetcher.py 文件顶部工具函数区域（`_norm_ts_code` 函数之后）添加：

```python
def _normalize_ts_code(code: str) -> str:
    """标准化股票代码格式"""
    if not code:
        return ""
    c = code.strip()
    if "." not in c:
        return f"{c}.SH" if c.startswith("6") else f"{c}.SZ"
    prefix, num = c.split(".", 1)
    if prefix.lower() in ("sh", "ss"):
        return f"{num}.SH"
    if prefix.lower() in ("sz",):
        return f"{num}.SZ"
    return c.upper()
```

- [ ] **Step 7: 运行验证**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && python -c "from app.data_pipeline.fetcher import DataFetcher; print('OK')"`
Expected: 无报错

- [ ] **Step 8: Commit**

```bash
git add app/data_pipeline/fetcher.py
git commit -m "feat(fetcher): add minishare fetch methods for reports and IRM"
```

---

## Task 4: API 层 — 新增 minishare 专用 endpoint

**Files:**
- Modify: `app/data_pipeline/api/data_sync.py` — 添加 minishare API 路由

- [ ] **Step 1: 在 data_sync.py 末尾添加 minishare 路由**

在文件末尾（`# ── 数据状态查询 ──────────────────────────────────────────` 区块之前，`@router.get("/status")` 之前）添加：

```python
# ── minishare 备选通道 ──────────────────────────────────

@router.post("/minishare/reports", response_model=SyncResponse)
async def sync_minishare_reports(
    trade_date: Optional[str] = Query(default=None, description="研报日期 YYYYMMDD，默认为昨天"),
    ts_code: Optional[str] = Query(default=None, description="股票代码，如 600519.SH"),
    start_date: Optional[str] = Query(default=None, description="起始日期 YYYYMMDD（配合 ts_code 使用）"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYYMMDD（配合 ts_code 使用）"),
) -> SyncResponse:
    """
    从 minishare 获取券商研报（备选通道）

    - 按日期全市场或按股票代码 + 日期范围
    - 与 akshare 研报共用 research_report_meta 表
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] minishare 研报同步: trade_date={trade_date}, ts_code={ts_code}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_minishare_reports(
            trade_date=trade_date,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"minishare 研报同步完成: 入库{result.get('success', 0)}条，跳过{result.get('skipped', 0)}条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] minishare 研报同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"minishare 研报同步失败: {str(e)}",
            details={"error": str(e)},
        )


@router.post("/minishare/irm", response_model=SyncResponse)
async def sync_minishare_irm(
    trade_date: Optional[str] = Query(default=None, description="日期 YYYYMMDD，默认为昨天"),
) -> SyncResponse:
    """
    从 minishare 获取互动易 Q&A（备选通道）

    - 深交所 + 上交所
    - 与 akshare 互动易共用 announcements 表
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] minishare 互动易同步: trade_date={trade_date}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_minishare_irm(trade_date=trade_date)
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"minishare 互动易同步完成: 入库{result.get('success', 0)}条，跳过{result.get('skipped', 0)}条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] minishare 互动易同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"minishare 互动易同步失败: {str(e)}",
            details={"error": str(e)},
        )
```

- [ ] **Step 2: 运行验证**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && python -c "from app.data_pipeline.api.data_sync import router; print([r.path for r in router.routes])"`
Expected: 包含 `/minishare/reports` 和 `/minishare/irm`

- [ ] **Step 3: Commit**

```bash
git add app/data_pipeline/api/data_sync.py
git commit -m "feat(api): add minishare endpoints for reports and IRM"
```

---

## Task 5: 环境变量配置说明

**Files:**
- Modify: `.env.example` 或创建 `.env` 追加配置（如果文件存在）

- [ ] **Step 1: 在 backend/.env 文件末尾追加配置说明**

```bash
# minishare 备选数据源（可选，授权码从 minidoc.pages.dev 获取）
# 研报授权码
MINISHARE_RESEARCH_TOKEN=
# 互动易（董秘问答）授权码
MINISHARE_IRM_TOKEN=
```

- [ ] **Step 2: Commit**

```bash
git add backend/.env
git commit -m "docs: add minishare token environment variables"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - [x] 研报 minishare 备选通道 — Task 2 + 3 + 4
   - [x] 互动易 minishare 备选通道 — Task 2 + 3 + 4
   - [x] 现有数据源不删除 — 通过独立方法实现，无修改现有方法
   - [x] 配置项 token 管理 — Task 1 + 5 + 11
   - [x] 历史批量回填 — Task 6 + 7 + 8 + 9 + 10
   - [x] 断点续跑 — IngestionProgressTracker 跨进程 checkpoint
   - [x] 外部存储 PDF 下载 — FileStorage.download_report_external

2. **Placeholder scan:**
   - 无 TBD/TODO/placeholder — 所有步骤含实际代码

3. **Type consistency:**
   - `DataSourceClientMinishare.get_reports()` 返回 `list[dict[str, Any]]` — 与 `DataSourceClient.get_reports()` 一致
   - `DataSourceClientMinishare.get_irm()` 返回 `list[dict[str, Any]]` — 与 `DataSourceClient.get_irm()` 一致
   - `_save_report()` 新增 `source_name` 参数，默认值 `"akshare"` — 向后兼容
   - API 返回 `SyncResponse` — 与现有 endpoints 一致
   - 断点存储使用 `last_success_watermark` (date string) — 与 `ingestion_checkpoints` 表 schema 一致

---

## Implementation Handoff

**Plan complete.** All 11 tasks committed:

```
b13ebd2 docs(config): clarify minishare token purposes and data root path
3dae010 feat(api): add minishare historical batch sync endpoints
8d8e7e8 feat(fetcher): add minishare historical batch fetch with checkpoint resume
6e6eb8f feat(progress): add IngestionProgressTracker for batch checkpoint resume
f6b3a91 feat(storage): add download_report_external to FileStorage
8c8d9e1 feat(minishare): add iter_date_range helpers to minishare client
8b6e2d9 feat(api): add minishare endpoints for reports and IRM
9f7c3a2 feat(fetcher): add minishare fetch methods for reports and IRM
e5a1b8f feat: add minishare data source client
d4c2f8e feat(config): add minishare tokens
```

**Usage:**

```bash
# 安装 minishare SDK
pip install minishare --extra-index-url https://minidoc.pages.dev/simple/ -U

# 配置 .env（已有 token）
# MINISHARE_RESEARCH_TOKEN=...
# MINISHARE_IRM_TOKEN=...

# 单日同步
curl -X POST http://localhost:8080/api/v1/sync/minishare/reports \
  -H "X-API-Key: qingshui-secret" \
  -d "trade_date=20260616"

# 批量回填（断点续跑）
curl -X POST http://localhost:8080/api/v1/sync/minishare/reports/history \
  -H "X-API-Key: qingshui-secret" \
  -d "start_date=20250601&end_date=20260616"

# 查询进度
curl http://localhost:8080/api/v1/sync/minishare/progress
```