#!/usr/bin/env python3
"""回补被清空的公告 PDF（run on chemagent）。

用途：历史清理把 ``minishare_announcements.file_path`` 置空，但
``evidence_at`` 仍非空 —— 这些行已经据此构建过 evidence，原文 PDF 却是
产物阅读器的取数来源。本脚本按 canonical 命名重新下载这些 PDF，并只回写
``file_path`` / ``download_status``。

铁律：
- 绝不删除、绝不覆盖已存在的文件；canonical 目标已存在即 ``skip``。
- 绝不清空 ``file_path``；只有下载成功后才写入。
- ``--dry-run`` 不触网、不落盘、不写库，只打印候选。

用法（chemagent 上经 scheduler 容器执行）：
    docker exec qingshui_scheduler python scripts/backfill_announcement_pdfs.py --limit 20 --dry-run
    docker exec qingshui_scheduler python scripts/backfill_announcement_pdfs.py --since 20260101
    docker exec qingshui_scheduler python scripts/backfill_announcement_pdfs.py --ann-ids 2200763,2200764
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import time
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import bindparam, text

from app.config import settings
from app.data_pipeline.file_storage import FileStorage
from app.knowledge.pdf_store import canonical_pdf_relpath

logger = logging.getLogger("backfill_announcement_pdfs")

# 每个候选最多尝试次数（含首次）。
ATTEMPTS = 3
# --sleep 的抖动比例：实际等待 = sleep_s * [1-J, 1+J]。
JITTER_RATIO = 0.25

_SQL_BASE = """SELECT id, ts_code, ann_date, title, source_url, file_path
FROM minishare_announcements
WHERE evidence_at IS NOT NULL
  AND (file_path IS NULL OR file_path = '')"""

_SQL_ORDER = """ORDER BY ann_date DESC
LIMIT :limit"""

_DATE_SHAPES = ("%Y%m%d", "%Y-%m-%d")


def _ann_date_token(ann_date: Any) -> str:
    """把 ``date`` / ``datetime`` / ``YYYY-MM-DD`` 统一成 ``YYYYMMDD``。

    无法解析的值原样返回，交由 ``canonical_pdf_relpath`` 归入 ``unknown`` 月。
    """
    if isinstance(ann_date, datetime):
        return ann_date.strftime("%Y%m%d")
    if isinstance(ann_date, date):
        return ann_date.strftime("%Y%m%d")
    candidate = str(ann_date or "").strip()
    for shape in _DATE_SHAPES:
        try:
            return datetime.strptime(candidate, shape).strftime("%Y%m%d")
        except ValueError:
            continue
    return candidate


def backfill_target_path(
    ts_code: str,
    ann_date: Any,
    ann_id: str | int,
    root: Path | str,
) -> Path:
    """canonical 落盘目标：``{root}/notices/{ts}/{YYYY-MM}/{ann_id}.pdf``。

    命名规则委托 ``pdf_store.canonical_pdf_relpath``，此处不复制。
    """
    return Path(root) / canonical_pdf_relpath(ts_code, _ann_date_token(ann_date), ann_id)


def plan_download(candidate: dict[str, Any], root: Path | str) -> str:
    """幂等闸门：目标已存在返回 ``"skip"``，否则 ``"download"``。

    用 ``exists()`` 而非 ``is_file()``：目标位置哪怕是目录也算已存在，
    绝不覆盖。
    """
    target = backfill_target_path(
        candidate["ts_code"],
        candidate["ann_date"],
        candidate["id"],
        root,
    )
    return "skip" if target.exists() else "download"


def build_candidates_sql(*, since: bool = False, ann_ids: bool = False) -> str:
    """候选查询：已建 evidence 但 ``file_path`` 为空的行，最新公告优先。"""
    conditions = [_SQL_BASE]
    if since:
        conditions.append("  AND ann_date >= :since")
    if ann_ids:
        conditions.append("  AND id IN :ann_ids")
    conditions.append(_SQL_ORDER)
    return "\n".join(conditions)


def _parse_since(raw: str) -> date:
    candidate = raw.strip()
    for shape in _DATE_SHAPES:
        try:
            return datetime.strptime(candidate, shape).date()
        except ValueError:
            continue
    raise ValueError(f"无法解析 --since={raw!r}，需为 YYYYMMDD 或 YYYY-MM-DD")


def _parse_ann_ids(raw: str | None) -> list[int]:
    if raw is None:
        return []
    ids: list[int] = []
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError as exc:
            raise ValueError(f"无法解析 --ann-ids 中的 {token!r}，需为整数") from exc
    return ids


def _resolve_root() -> Path:
    """canonical 存储根，与 ``FileStorage._data_root`` 同一口径。"""
    return Path(getattr(settings, "pdf_storage_root", None) or settings.minishare_data_root)


def _make_storage() -> FileStorage:
    return FileStorage()


def _sleep_with_jitter(sleep_s: float) -> None:
    if sleep_s <= 0:
        return
    time.sleep(sleep_s * random.uniform(1 - JITTER_RATIO, 1 + JITTER_RATIO))


def _attempt_download(
    storage: FileStorage,
    candidate: dict[str, Any],
    root: Path | str,
    sleep_s: float,
) -> Path | None:
    """下载单个候选，最多 ``ATTEMPTS`` 次；成功返回落盘路径。"""
    url = str(candidate.get("source_url") or "").strip()
    ann_id = candidate["id"]
    if not url:
        logger.warning("跳过 id=%s：source_url 为空，无法下载", ann_id)
        return None

    filename = f"{ann_id}.pdf"
    pub_date = _ann_date_token(candidate["ann_date"])
    expected = backfill_target_path(candidate["ts_code"], candidate["ann_date"], ann_id, root)

    for attempt in range(1, ATTEMPTS + 1):
        saved: Path | None = None
        try:
            result = storage.download_notice(url, candidate["ts_code"], filename, pub_date)
        except Exception:
            logger.exception("id=%s 第 %s/%s 次下载抛异常", ann_id, attempt, ATTEMPTS)
            result = None
        if result is not None:
            saved = Path(result)
            if saved != expected:
                logger.warning("id=%s 落盘路径与 canonical 目标不一致: %s != %s", ann_id, saved, expected)
            logger.info("id=%s 下载成功 -> %s", ann_id, saved)
            return saved
        logger.warning("id=%s 第 %s/%s 次下载失败", ann_id, attempt, ATTEMPTS)
        if attempt < ATTEMPTS:
            _sleep_with_jitter(sleep_s)
    return None


async def _fetch_candidates(stmt: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
    from app.core.database import engine

    async with engine.connect() as conn:
        result = await conn.execute(stmt, params)
        return [dict(row._mapping) for row in result]


async def _write_back(ann_id: int, path: Path) -> None:
    """下载成功后回写 ``file_path``；只在成功后调用，绝不置空。"""
    from app.core.database import engine

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE minishare_announcements "
                "SET file_path = :file_path, download_status = 'stored' "
                "WHERE id = :ann_id"
            ),
            {"file_path": str(path), "ann_id": ann_id},
        )


async def run(
    *,
    dry_run: bool,
    limit: int | None,
    since: str | None,
    sleep_s: float,
    ann_ids: Sequence[int] | None = None,
) -> dict[str, int]:
    """执行回补，返回 ``{"candidates","downloaded","skipped","failed"}`` 计数。"""
    ann_id_list = list(ann_ids or [])
    stmt = text(build_candidates_sql(since=since is not None, ann_ids=bool(ann_id_list)))
    params: dict[str, Any] = {"limit": limit}
    if since is not None:
        params["since"] = _parse_since(since)
    if ann_id_list:
        stmt = stmt.bindparams(bindparam("ann_ids", expanding=True))
        params["ann_ids"] = ann_id_list

    counts = {"candidates": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    rows = await _fetch_candidates(stmt, params)
    root = _resolve_root()
    storage: FileStorage | None = None

    for index, candidate in enumerate(rows):
        counts["candidates"] += 1
        ann_id = candidate["id"]
        target = backfill_target_path(candidate["ts_code"], candidate["ann_date"], ann_id, root)
        if plan_download(candidate, root) == "skip":
            counts["skipped"] += 1
            logger.info("skip id=%s：目标已存在 %s", ann_id, target)
            continue
        if dry_run:
            logger.info(
                "[dry-run] would download id=%s %s %s -> %s",
                ann_id,
                candidate["ts_code"],
                candidate.get("title"),
                target,
            )
            continue

        if storage is None:
            storage = _make_storage()
        saved = _attempt_download(storage, candidate, root, sleep_s)
        if saved is None:
            counts["failed"] += 1
        else:
            try:
                await _write_back(ann_id, saved)
            except Exception:
                logger.exception("id=%s 下载成功但回写 file_path 失败", ann_id)
                counts["failed"] += 1
            else:
                counts["downloaded"] += 1
        if index + 1 < len(rows):
            _sleep_with_jitter(sleep_s)

    return counts


async def _run_and_dispose(**kwargs: Any) -> dict[str, int]:
    from app.core.database import engine

    try:
        return await run(**kwargs)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回补被清空的公告 PDF（canonical 命名，已存在即跳过）")
    parser.add_argument("--dry-run", action="store_true", help="只打印候选，不触网/不落盘/不写库")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少条候选（默认不限）")
    parser.add_argument("--since", default=None, help="只处理 ann_date >= 该日期的公告（YYYYMMDD 或 YYYY-MM-DD）")
    parser.add_argument("--sleep", type=float, default=1.0, help="每条之间的基础间隔秒数（带抖动）")
    parser.add_argument("--ann-ids", default=None, help="逗号分隔的公告 id，仅处理这些行")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        ann_ids = _parse_ann_ids(args.ann_ids)
        if args.since is not None:
            _parse_since(args.since)
    except ValueError as exc:
        parser.error(str(exc))

    counts = asyncio.run(
        _run_and_dispose(
            dry_run=args.dry_run,
            limit=args.limit,
            since=args.since,
            sleep_s=args.sleep,
            ann_ids=ann_ids,
        )
    )
    logger.info(
        "完成%s：候选 %s / 下载 %s / 跳过 %s / 失败 %s",
        "（dry-run）" if args.dry_run else "",
        counts["candidates"],
        counts["downloaded"],
        counts["skipped"],
        counts["failed"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
