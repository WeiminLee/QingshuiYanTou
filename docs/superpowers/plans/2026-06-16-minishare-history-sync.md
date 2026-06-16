# minishare 历史数据批量获取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 minishare 一次性回填过去一年的研报和互动易数据（含 PDF 下载），支持断点续跑，不重复下载不重复入库。

**Architecture:**
1. 新增 `minishare_data_root` 配置指向 `/home/lwm/qingshui_data`（项目外部）
2. `minishare_client.py` 增强：支持日期范围遍历
3. `fetcher.py` 新增历史批量方法，复用 `IngestionProgressTracker` 做断点续跑（watermark=日期）
4. PDF 存到外部路径，`research_report_meta.file_path` 记录路径
5. 数据库索引已有（`file_name` UNIQUE / `cninfo_id` UNIQUE），确保 `research_report_meta` 和 `announcements` 表的索引覆盖新字段

**Tech Stack:** minishare SDK, pandas, asyncio, SQLAlchemy, IngestionProgressTracker

---

## File Structure

- Modify: `app/config.py` — 新增 `minishare_data_root` 路径配置
- Modify: `app/data_pipeline/minishare_client.py` — 新增日期范围遍历方法
- Modify: `app/data_pipeline/fetcher.py` — 新增历史批量 fetch 方法 + PDF 下载
- Modify: `app/data_pipeline/api/data_sync.py` — 新增历史批量同步 API endpoint
- Modify: `app/data_pipeline/file_storage.py` — 支持外部存储路径
- Modify: `.env.example` — 新增配置说明

---

## Task 1: 配置项 — 添加 minishare_data_root 到 config.py

**Files:**
- Modify: `app/config.py` — 在 `data_assets_root` 附近添加 `minishare_data_root`

- [ ] **Step 1: 添加配置字段**

在 `data_assets_root` 配置行之后添加：
```python
    # minishare 外部数据存储路径（PDF/文件，与项目 storage 分离）
    minishare_data_root: Path = Path("/home/lwm/qingshui_data")
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -c "from app.config import settings; print(settings.minishare_data_root)"`
Expected: `/home/lwm/qingshui_data`

- [ ] **Step 3: Commit**

```bash
git add app/config.py && git commit -m "feat(config): add minishare_data_root external storage path"
```

---

## Task 2: FileStorage 支持外部存储路径

**Files:**
- Modify: `app/data_pipeline/file_storage.py`

- [ ] **Step 1: 修改 FileStorage.__init__ 支持外部路径**

找到 `__init__` 方法中：
```python
        from app.config import settings

        # 使用配置中的存储路径
        storage_base = Path(settings.storage_dir) if hasattr(settings, "storage_dir") else Path(__file__).resolve().parent.parent.parent / "storage"
```

改为：
```python
        from app.config import settings

        # 使用配置中的存储路径
        storage_base = Path(settings.storage_dir) if hasattr(settings, "storage_dir") else Path(__file__).resolve().parent.parent.parent / "storage"

        # minishare 外部存储路径（研报/互动易 PDF）
        self.external_reports_dir = reports_dir or (Path(settings.minishare_data_root) / "reports")
        self.external_notices_dir = notices_dir or (Path(settings.minishare_data_root) / "irm")
```

找到 `self.reports_dir.mkdir` 附近，添加：
```python
        # 确保外部存储目录存在
        self.external_reports_dir.mkdir(parents=True, exist_ok=True)
        self.external_notices_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: 修改 `_get_report_path` 支持 external 模式**

在 `FileStorage` 类中添加新方法：
```python
    def _get_external_report_path(
        self,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> tuple[Optional[Path], str | None]:
        """研报外部存储路径：minishare_data_root/reports/{ts_code}/{YYYY-MM}/"""
        if ts_code and ts_code.strip():
            sub_dir = ts_code
        elif inst_csname and self._is_broker_or_consult(inst_csname):
            safe_name = inst_csname[:30].replace("/", "_").replace("\\", "_")
            sub_dir = f"_industry/{safe_name}"
        else:
            return None, REPORT_PATH_NONE

        if trade_date and len(trade_date) >= 6:
            year_month = f"{trade_date[:4]}-{trade_date[4:6]}"
        else:
            year_month = "unknown"

        storage_dir = self.external_reports_dir / sub_dir / year_month
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir / filename, REPORT_PATH_STOCK

    def save_report_external(
        self,
        content: bytes,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> Optional[Path]:
        """保存研报 PDF 到外部存储"""
        if not content[:5] == b"%PDF-":
            logger.warning("内容不是 PDF，放弃保存")
            return None
        try:
            file_path, storage_type = self._get_external_report_path(
                ts_code, inst_csname, trade_date, filename
            )
            if file_path is None:
                logger.debug(f"研报外部存储跳过（无 ts_code）: {filename}")
                return None
            file_path.write_bytes(content)
            logger.info(f"研报外部保存成功: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"研报外部保存失败: {e}")
            return None

    def download_report_external(
        self,
        url: str,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> Optional[Path]:
        """下载并保存研报 PDF 到外部存储"""
        try:
            file_path, storage_type = self._get_external_report_path(
                ts_code, inst_csname, trade_date, filename
            )
            if file_path is None:
                logger.debug(f"研报外部下载跳过（无 ts_code）: {filename}")
                return None
            if file_path.exists():
                logger.info(f"研报已存在，跳过下载: {file_path}")
                return file_path
            get_cninfo_pdf_limiter().wait_and_acquire()
            response = requests.get(url, timeout=30, headers=HTTP_HEADERS)
            response.raise_for_status()

            content = response.content
            if not content[:5] == b"%PDF-":
                logger.warning(f"下载内容不是 PDF [{url[:80]}]")
                return None

            file_path.write_bytes(content)
            logger.info(f"研报外部下载成功: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"研报外部下载失败 [{url}]: {e}")
            return None
```

- [ ] **Step 3: 验证**

Run: `.venv/bin/python -c "from app.data_pipeline.file_storage import FileStorage; f = FileStorage(); print(f.external_reports_dir); print(f.external_notices_dir)"`
Expected: 两个路径都存在且在 `/home/lwm/qingshui_data/` 下

- [ ] **Step 4: Commit**

```bash
git add app/data_pipeline/file_storage.py && git commit -m "feat(file_storage): add external storage support for minishare PDFs"
```

---

## Task 3: minishare_client 增强 — 日期范围遍历

**Files:**
- Modify: `app/data_pipeline/minishare_client.py` — 新增 `iter_reports_by_date_range` 和 `iter_irm_by_date_range`

- [ ] **Step 1: 添加迭代器方法**

在 `DataSourceClientMinishare` 类末尾（在最后一个方法之后）添加：

```python
    def iter_reports_by_date_range(
        self,
        start_date: str,
        end_date: str,
        batch_size: int = 5000,
    ):
        """按日期范围遍历研报数据（生成器）。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            batch_size: 每次请求的最大条数（minishare 限制）

        Yields:
            list[dict]: 每天的研报记录列表
        """
        if not self.research_available:
            return

        from datetime import datetime, timedelta

        current = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        while current <= end:
            date_str = current.strftime("%Y%m%d")
            try:
                df = self._research_api.research_report(trade_date=date_str)
                if df is not None and len(df) > 0:
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
                    yield date_str, records
                else:
                    yield date_str, []
            except Exception as e:
                logger.warning(f"minishare 研报 {date_str} 失败: {e}")
                yield date_str, []
            current += timedelta(days=1)

    def iter_irm_by_date_range(
        self,
        start_date: str,
        end_date: str,
    ):
        """按日期范围遍历互动易 Q&A（生成器，上证 + 深证）。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Yields:
            tuple(date_str, list[dict]): 每天的互动易记录列表
        """
        if not self.irm_available:
            return

        from datetime import datetime, timedelta

        current = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        while current <= end:
            date_str = current.strftime("%Y%m%d")
            records: list[dict[str, Any]] = []

            # 上证
            try:
                df_sh = self._irm_api.irm_qa_sh(trade_date=date_str)
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
            except Exception as e:
                logger.warning(f"minishare 上证互动易 {date_str} 失败: {e}")

            # 深证
            try:
                df_sz = self._irm_api.irm_qa_sz(trade_date=date_str)
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
            except Exception as e:
                logger.warning(f"minishare 深证互动易 {date_str} 失败: {e}")

            yield date_str, records
            current += timedelta(days=1)
```

- [ ] **Step 2: 添加缺失的 datetime import**

在文件顶部找到 `from typing import Any, Optional`，在 `Optional` 之后添加 `from datetime import datetime, timedelta`（如果还没有的话）。或者在类方法内部从 datetime import。

实际上上面的代码在方法内部已经导入了，不需要修改顶部。

- [ ] **Step 3: 验证**

Run: `.venv/bin/python -c "from app.data_pipeline.minishare_client import DataSourceClientMinishare; c = DataSourceClientMinishare(); print('iter_reports:', hasattr(c, 'iter_reports_by_date_range'), 'iter_irm:', hasattr(c, 'iter_irm_by_date_range'))"`
Expected: True True

- [ ] **Step 4: Commit**

```bash
git add app/data_pipeline/minishare_client.py && git commit -m "feat(minishare_client): add date range iterator methods"
```

---

## Task 4: DataFetcher — 新增历史批量 fetch 方法

**Files:**
- Modify: `app/data_pipeline/fetcher.py` — 在 `DataFetcher` 类末尾添加两个新方法

- [ ] **Step 1: 添加 fetch_minishare_reports_history 方法**

在 `fetch_minishare_irm` 方法之后添加：

```python
    async def fetch_minishare_reports_history(
        self,
        start_date: str,
        end_date: str,
        download_pdf: bool = True,
    ) -> dict[str, int]:
        """从 minishare 批量回填历史研报（按日期遍历，断点续跑）。

        断点机制：使用 IngestionProgressTracker 的 checkpoint，
        记录 last_success_watermark = 已完成的最大日期（当天数据全部入库+下载完成）。
        下次启动从 watermark + 1 天继续。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            download_pdf: 是否下载 PDF（默认 True）
        """
        task_id = generate_task_id()
        set_task_id(task_id)

        if not self.minishare_client.research_available:
            logger.warning("minishare 研报 token 未配置，跳过")
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        tracker = IngestionProgressTracker(
            source="minishare",
            task_name="reports_history",
            scope=f"{start_date}_{end_date}",
        )
        await tracker.ensure_tables()

        # 读取 checkpoint，从断点继续
        checkpoint = await tracker.get_checkpoint()
        if checkpoint and checkpoint.get("last_success_watermark"):
            resume_date = checkpoint["last_success_watermark"]
            from datetime import datetime, timedelta
            resume_date_next = (datetime.strptime(resume_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
            logger.info(f"研报历史同步断点续跑: {start_date}~{end_date}，从 {resume_date_next} 开始（已完成 {resume_date}）")
            start_date = resume_date_next

        run_ctx = await tracker.start_run(
            from_watermark=start_date,
            to_watermark=end_date,
            metadata={"download_pdf": download_pdf, "source": "minishare"},
        )

        logger.info("开始 minishare 研报历史同步: %s~%s", start_date, end_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"minishare 研报历史同步: {start_date}~{end_date}",
            task_id=task_id,
        )

        total_success = 0
        total_skipped = 0
        total_fail = 0
        total_downloaded = 0
        total_days = 0
        last_success_date = start_date

        for date_str, reports in self.minishare_client.iter_reports_by_date_range(start_date, end_date):
            total_days += 1

            if not reports:
                # 无数据日期也要更新 watermark
                await tracker.save_checkpoint(last_success_watermark=date_str, last_success_at=datetime.now(timezone.utc))
                await tracker.update_run(
                    run_ctx,
                    current_watermark=date_str,
                    total_items=total_days,
                    processed_items=total_days,
                )
                continue

            # EXISTS 预查询
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
                    ann_id = _stable_id("ms_report", date_str, title, inst_csname)

                candidates.append({
                    "ann_id": ann_id,
                    "ts_code": ts_code_val,
                    "title": title,
                    "inst_csname": inst_csname,
                    "author": author,
                    "url": url,
                })

            candidate_ids = [c["ann_id"] for c in candidates]
            existing: set[str] = set()
            if candidate_ids:
                try:
                    async with engine.connect() as conn:
                        rows = await conn.execute(
                            text("SELECT file_name FROM research_report_meta WHERE file_name = ANY(:ids)"),
                            {"ids": candidate_ids},
                        )
                        existing = {r[0] for r in rows.fetchall()}
                except Exception as exc:
                    logger.warning("研报预查询失败: %s", exc)

            day_success = day_skipped = day_fail = day_downloaded = 0
            for c in candidates:
                if c["ann_id"] in existing:
                    day_skipped += 1
                    continue

                # 下载 PDF
                file_path = None
                if download_pdf and c["url"]:
                    file_path = await asyncio.to_thread(
                        self.storage.download_report_external,
                        url=c["url"],
                        ts_code=c["ts_code"],
                        inst_csname=c["inst_csname"],
                        trade_date=date_str,
                        filename=f"{c['ann_id']}_{c['title'][:50].replace('/', '_')}.pdf",
                    )
                    if file_path is not None:
                        day_downloaded += 1

                saved = await self._save_report(
                    ann_id=c["ann_id"],
                    ts_code=c["ts_code"],
                    title=c["title"],
                    trade_date=date_str,
                    inst_csname=c["inst_csname"],
                    author=c["author"],
                    source_name="minishare",
                )
                if saved is True:
                    day_success += 1
                elif saved is None:
                    day_skipped += 1
                else:
                    day_fail += 1

            total_success += day_success
            total_skipped += day_skipped
            total_fail += day_fail
            total_downloaded += day_downloaded
            last_success_date = date_str

            # 保存 checkpoint（当天数据全部处理完）
            await tracker.save_checkpoint(
                last_success_watermark=date_str,
                last_success_at=datetime.now(timezone.utc),
            )
            await tracker.update_run(
                run_ctx,
                current_watermark=date_str,
                total_items=total_days,
                processed_items=total_days,
                success_count=total_success,
                skipped_count=total_skipped,
                downloaded_count=total_downloaded,
                fail_count=total_fail,
            )

            if total_days % 30 == 0:
                await tracker.event(
                    run_ctx,
                    stage="batch_progress",
                    message=f"研报历史同步进度: {date_str}",
                    total_items=total_days,
                    processed_items=total_days,
                    success_count=total_success,
                    skipped_count=total_skipped,
                    downloaded_count=total_downloaded,
                    fail_count=total_fail,
                    item_id=date_str,
                )

        await tracker.finish_run(
            run_ctx,
            status=SUCCESS if total_fail == 0 else PARTIAL,
            total_items=total_days,
            processed_items=total_days,
            success_count=total_success,
            skipped_count=total_skipped,
            downloaded_count=total_downloaded,
            fail_count=total_fail,
            current_watermark=last_success_date,
            last_item_id=last_success_date,
        )

        logger.info(
            "minishare 研报历史同步完成: %s~%s，日期 %d 天，入库 %d，跳过 %d，下载 %d，失败 %d",
            start_date, end_date, total_days, total_success, total_skipped, total_downloaded, total_fail,
        )
        return {
            "total_days": total_days,
            "success": total_success,
            "skipped": total_skipped,
            "downloaded": total_downloaded,
            "fail": total_fail,
            "source": "minishare",
        }
```

- [ ] **Step 2: 添加 fetch_minishare_irm_history 方法**

在 `fetch_minishare_reports_history` 之后添加：

```python
    async def fetch_minishare_irm_history(
        self,
        start_date: str,
        end_date: str,
    ) -> dict[str, int]:
        """从 minishare 批量回填历史互动易（按日期遍历，断点续跑）。

        断点机制：使用 IngestionProgressTracker 的 checkpoint，
        记录 last_success_watermark = 已完成的最大日期。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
        """
        task_id = generate_task_id()
        set_task_id(task_id)

        if not self.minishare_client.irm_available:
            logger.warning("minishare 互动易 token 未配置，跳过")
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        tracker = IngestionProgressTracker(
            source="minishare_irm",
            task_name="irm_history",
            scope=f"{start_date}_{end_date}",
        )
        await tracker.ensure_tables()

        # 读取 checkpoint，从断点继续
        checkpoint = await tracker.get_checkpoint()
        if checkpoint and checkpoint.get("last_success_watermark"):
            resume_date = checkpoint["last_success_watermark"]
            from datetime import datetime, timedelta
            resume_date_next = (datetime.strptime(resume_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
            logger.info(f"互动易历史同步断点续跑: {start_date}~{end_date}，从 {resume_date_next} 开始")
            start_date = resume_date_next

        run_ctx = await tracker.start_run(
            from_watermark=start_date,
            to_watermark=end_date,
            metadata={"source": "minishare"},
        )

        logger.info("开始 minishare 互动易历史同步: %s~%s", start_date, end_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"minishare 互动易历史同步: {start_date}~{end_date}",
            task_id=task_id,
        )

        total_success = 0
        total_skipped = 0
        total_fail = 0
        total_days = 0
        last_success_date = start_date

        for date_str, records in self.minishare_client.iter_irm_by_date_range(start_date, end_date):
            total_days += 1

            if not records:
                await tracker.save_checkpoint(last_success_watermark=date_str, last_success_at=datetime.now(timezone.utc))
                await tracker.update_run(
                    run_ctx,
                    current_watermark=date_str,
                    total_items=total_days,
                    processed_items=total_days,
                )
                continue

            day_success = day_skipped = day_fail = 0
            for rec in records:
                ts_code_raw = _norm_ts_code(rec.get("stock_code") or "")
                if ts_code_raw and "." not in ts_code_raw:
                    ts_code = _normalize_ts_code(ts_code_raw)
                else:
                    ts_code = ts_code_raw

                ok = await self._save_irm_record(ts_code or "UNKNOWN", rec)
                if ok is True:
                    day_success += 1
                elif ok is None:
                    day_skipped += 1
                else:
                    day_fail += 1

            total_success += day_success
            total_skipped += day_skipped
            total_fail += day_fail
            last_success_date = date_str

            await tracker.save_checkpoint(
                last_success_watermark=date_str,
                last_success_at=datetime.now(timezone.utc),
            )
            await tracker.update_run(
                run_ctx,
                current_watermark=date_str,
                total_items=total_days,
                processed_items=total_days,
                success_count=total_success,
                skipped_count=total_skipped,
                fail_count=total_fail,
            )

            if total_days % 30 == 0:
                await tracker.event(
                    run_ctx,
                    stage="batch_progress",
                    message=f"互动易历史同步进度: {date_str}",
                    total_items=total_days,
                    processed_items=total_days,
                    success_count=total_success,
                    skipped_count=total_skipped,
                    fail_count=total_fail,
                    item_id=date_str,
                )

        await tracker.finish_run(
            run_ctx,
            status=SUCCESS if total_fail == 0 else PARTIAL,
            total_items=total_days,
            processed_items=total_days,
            success_count=total_success,
            skipped_count=total_skipped,
            fail_count=total_fail,
            current_watermark=last_success_date,
            last_item_id=last_success_date,
        )

        logger.info(
            "minishare 互动易历史同步完成: %s~%s，日期 %d 天，入库 %d，跳过 %d，失败 %d",
            start_date, end_date, total_days, total_success, total_skipped, total_fail,
        )
        return {
            "total_days": total_days,
            "success": total_success,
            "skipped": total_skipped,
            "fail": total_fail,
            "source": "minishare",
        }
```

- [ ] **Step 3: 添加 save_checkpoint 到 IngestionProgressTracker**

`IngestionProgressTracker` 目前没有 `save_checkpoint` 方法。需要添加。找到 `progress.py` 文件末尾，添加：

```python
    async def save_checkpoint(
        self,
        last_success_watermark: str | None = None,
        last_attempt_watermark: str | None = None,
        last_success_at: datetime | None = None,
        last_attempt_at: datetime | None = None,
        last_status: str | None = None,
    ) -> None:
        """保存断点：更新 ingestion_checkpoints 表。"""
        await self.ensure_tables()
        now = datetime.now(timezone.utc)
        update: dict[str, Any] = {"last_attempt_at": last_attempt_at or now}
        if last_success_watermark is not None:
            update["last_success_watermark"] = last_success_watermark
        if last_attempt_watermark is not None:
            update["last_attempt_watermark"] = last_attempt_watermark
        if last_success_at is not None:
            update["last_success_at"] = last_success_at
        if last_attempt_at is not None:
            update["last_attempt_at"] = last_attempt_at
        if last_status is not None:
            update["last_status"] = last_status

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO ingestion_checkpoints (
                        source, task_name, scope,
                        last_success_watermark, last_attempt_watermark,
                        last_success_at, last_attempt_at, last_status
                    ) VALUES (
                        :source, :task_name, :scope,
                        :last_success_watermark, :last_attempt_watermark,
                        :last_success_at, :last_attempt_at, :last_status
                    )
                    ON CONFLICT (source, task_name, scope) DO UPDATE SET
                        last_success_watermark = EXCLUDED.last_success_watermark,
                        last_attempt_watermark = EXCLUDED.last_attempt_watermark,
                        last_success_at = EXCLUDED.last_success_at,
                        last_attempt_at = EXCLUDED.last_attempt_at,
                        last_status = EXCLUDED.last_status,
                        updated_at = NOW()
                    """
                ),
                {
                    "source": self.source,
                    "task_name": self.task_name,
                    "scope": self.scope,
                    "last_success_watermark": update.get("last_success_watermark"),
                    "last_attempt_watermark": update.get("last_attempt_watermark"),
                    "last_success_at": update.get("last_success_at"),
                    "last_attempt_at": update.get("last_attempt_at"),
                    "last_status": update.get("last_status"),
                },
            )
```

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -c "from app.data_pipeline.fetcher import DataFetcher; f = DataFetcher(); print('fetch_minishare_reports_history:', hasattr(f, 'fetch_minishare_reports_history')); print('fetch_minishare_irm_history:', hasattr(f, 'fetch_minishare_irm_history'))"`
Expected: True True

- [ ] **Step 5: Commit**

```bash
git add app/data_pipeline/fetcher.py app/data_pipeline/progress.py && git commit -m "feat(fetcher): add minishare historical batch fetch with checkpoint resume"
```

---

## Task 5: API 层 — 新增历史批量同步 endpoint

**Files:**
- Modify: `app/data_pipeline/api/data_sync.py`

- [ ] **Step 1: 添加历史批量同步 endpoint**

在 minishare 备选通道区块末尾（在 `# ── 数据状态查询` 之前）添加：

```python
# ── minishare 历史批量同步 ────────────────────────────────

@router.post("/minishare/reports/history", response_model=SyncResponse)
async def sync_minishare_reports_history(
    start_date: str = Query(..., description="起始日期 YYYYMMDD，如 20250601"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD，如 20260616"),
    download_pdf: bool = Query(default=True, description="是否下载 PDF"),
) -> SyncResponse:
    """
    从 minishare 批量回填历史研报（断点续跑）

    - 从 start_date 到 end_date 逐日遍历
    - 使用 IngestionProgressTracker checkpoint，重复运行不会从头开始
    - PDF 存到外部存储（/home/lwm/qingshui_data/reports/）
    - 默认下载 PDF
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] minishare 研报历史同步: {start_date}~{end_date}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_minishare_reports_history(
            start_date=start_date,
            end_date=end_date,
            download_pdf=download_pdf,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"minishare 研报历史同步完成: {result.get('total_days', 0)} 天，入库 {result.get('success', 0)} 条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] minishare 研报历史同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"minishare 研报历史同步失败: {str(e)}",
            details={"error": str(e)},
        )


@router.post("/minishare/irm/history", response_model=SyncResponse)
async def sync_minishare_irm_history(
    start_date: str = Query(..., description="起始日期 YYYYMMDD，如 20250601"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD，如 20260616"),
) -> SyncResponse:
    """
    从 minishare 批量回填历史互动易（断点续跑）

    - 从 start_date 到 end_date 逐日遍历（上证 + 深证）
    - 使用 IngestionProgressTracker checkpoint，重复运行不会从头开始
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] minishare 互动易历史同步: {start_date}~{end_date}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_minishare_irm_history(
            start_date=start_date,
            end_date=end_date,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"minishare 互动易历史同步完成: {result.get('total_days', 0)} 天，入库 {result.get('success', 0)} 条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] minishare 互动易历史同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"minishare 互动易历史同步失败: {str(e)}",
            details={"error": str(e)},
        )


@router.get("/minishare/progress", response_model=dict)
async def get_minishare_progress() -> dict:
    """
    查询 minishare 数据同步进度（断点状态）

    返回研报和互动易历史同步的 checkpoint 信息
    """
    from app.data_pipeline.progress import IngestionProgressTracker

    reports_tracker = IngestionProgressTracker(
        source="minishare",
        task_name="reports_history",
        scope="*",
    )
    irm_tracker = IngestionProgressTracker(
        source="minishare_irm",
        task_name="irm_history",
        scope="*",
    )

    await reports_tracker.ensure_tables()
    await irm_tracker.ensure_tables()

    # 查询所有相关 checkpoint
    from sqlalchemy import text
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT source, task_name, scope,
                       last_success_watermark, last_success_at,
                       last_status, updated_at
                FROM ingestion_checkpoints
                WHERE source IN ('minishare', 'minishare_irm')
                ORDER BY updated_at DESC
                """
            )
        )
        checkpoints = [dict(row._mapping) for row in rows.fetchall()]

    return {"checkpoints": checkpoints}
```

- [ ] **Step 2: 添加 engine import**

在 `data_sync.py` 顶部已有 `from app.data_pipeline.fetcher import DataFetcher`，需要确认 `from app.core.database import engine` 在文件中（`get_sync_status` 方法里已有，不需要额外添加）。

- [ ] **Step 3: 验证**

Run: `.venv/bin/python -c "from app.data_pipeline.api.data_sync import router; print([r.path for r in router.routes if 'minishare' in r.path])"`
Expected: 包含 `/minishare/reports`, `/minishare/irm`, `/minishare/reports/history`, `/minishare/irm/history`, `/minishare/progress`

- [ ] **Step 4: Commit**

```bash
git add app/data_pipeline/api/data_sync.py && git commit -m "feat(api): add minishare historical batch sync endpoints"
```

---

## Task 6: 环境变量配置说明

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: 添加配置说明**

在 `.env.example` 文件末尾追加：

```bash
# minishare 外部数据存储路径（PDF 存放位置，项目外部）
MINISHARE_DATA_ROOT=/home/lwm/qingshui_data
```

- [ ] **Step 2: Commit**

```bash
git add .env.example && git commit -m "docs: add minishare_data_root to .env.example"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - [x] 研报一年历史数据回填 — Task 3 + 4 + 5
   - [x] 互动易一年历史数据回填（上证+深证）— Task 3 + 4 + 5
   - [x] PDF 存到外部路径 — Task 1 + 2
   - [x] 断点续跑（checkpoint）— Task 4
   - [x] 避免重复下载（文件存在跳过）— Task 2 (`download_report_external` 中 `if file_path.exists()`)
   - [x] 避免重复入库（EXISTS 预查询）— Task 4
   - [x] 进度查询 API — Task 5
   - [x] 数据库索引 — 已有 UNIQUE 索引，无需额外修改

2. **Placeholder scan:**
   - 无 TBD/TODO/placeholder

3. **Type consistency:**
   - `iter_reports_by_date_range` yields `(date_str, records)` — 与调用方一致
   - `iter_irm_by_date_range` yields `(date_str, records)` — 与调用方一致
   - `save_checkpoint` 参数与 checkpoint 表字段一致

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-16-minishare-history-sync.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**