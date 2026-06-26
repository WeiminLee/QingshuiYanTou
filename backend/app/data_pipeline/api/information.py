"""
信息类 API

- 互动易Q&A查询（MongoDB qa_interactive）
- 公告列表查询（PostgreSQL announcements）
- 研报元数据查询（PostgreSQL research_report_meta）
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.mongodb import get_mongo_db
from app.models.models import Announcement, ResearchReportMeta

router = APIRouter()
logger = logging.getLogger(__name__)


# ── 财联社电报 ────────────────────────────────────────


@router.get("/cls-news")
async def get_cls_news(
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
):
    """
    查询财联社电报（MongoDB cls_news）
    按发布时间降序，保留最新3天数据
    """
    db = get_mongo_db()
    collection = db["cls_news"]

    total = await collection.count_documents({})

    cursor = (
        collection.find(
            {},
            {"_id": 0},
        )
        .sort("pub_date", -1)
        .sort("pub_time", -1)
        .skip(skip)
        .limit(limit)
    )

    items = []
    async for doc in cursor:
        items.append(
            {
                "title": doc.get("title"),
                "content": doc.get("content"),
                "pub_date": doc.get("pub_date"),
                "pub_time": doc.get("pub_time"),
                "full_datetime": doc.get("full_datetime"),
                "category": doc.get("category"),
                "signals": doc.get("signals", []),
            }
        )

    return {"items": items, "total": total}


# ── 互动易Q&A ────────────────────────────────────────


@router.get("/qa")
async def get_qa_interactive_all(
    ts_code: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """
    查询互动易Q&A全量或个股列表（MongoDB）
    不传 ts_code → 全量；传 ts_code → 单只股票
    """
    db = get_mongo_db()
    collection = db["qa_interactive"]

    query = {}
    if ts_code:
        query["ts_code"] = ts_code

    total = await collection.count_documents(query)

    cursor = (
        collection.find(
            query,
            {"_id": 0},
        )
        .sort("ann_date", -1)
        .skip(skip)
        .limit(limit)
    )

    items = []
    async for doc in cursor:
        items.append(
            {
                "exchange": doc.get("exchange"),
                "ts_code": doc.get("ts_code"),
                "ann_date": doc.get("ann_date"),
                "question": doc.get("question"),
                "answer": doc.get("answer"),
                "q_time": doc.get("q_time"),
                "a_time": doc.get("a_time"),
                "signals": doc.get("signals", []),
                "analysis_status": doc.get("analysis_status", "pending"),
            }
        )

    return {"items": items, "total": total}


@router.get("/qa/{ts_code}")
async def get_qa_interactive(
    ts_code: str,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """
    查询个股互动易Q&A（MongoDB）
    按 ann_date 降序排列
    """
    db = get_mongo_db()
    collection = db["qa_interactive"]

    cursor = (
        collection.find(
            {"ts_code": ts_code},
            {"_id": 0},
        )
        .sort("ann_date", -1)
        .skip(skip)
        .limit(limit)
    )

    items = []
    async for doc in cursor:
        items.append(
            {
                "exchange": doc.get("exchange"),
                "ts_code": doc.get("ts_code"),
                "ann_date": doc.get("ann_date"),
                "question": doc.get("question"),
                "answer": doc.get("answer"),
                "q_time": doc.get("q_time"),
                "a_time": doc.get("a_time"),
                "signals": doc.get("signals", []),
                "analysis_status": doc.get("analysis_status", "pending"),
            }
        )

    return {"ts_code": ts_code, "items": items, "total": len(items)}


# ── 公告列表 ─────────────────────────────────────────


@router.get("/announcements/{ts_code}")
async def get_announcements(
    ts_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """查询个股公告（PostgreSQL）"""
    stmt = select(Announcement).where(Announcement.ts_code == ts_code)

    if start_date:
        start = datetime.strptime(start_date, "%Y%m%d").date()
        stmt = stmt.where(Announcement.ann_date >= start)
    if end_date:
        end = datetime.strptime(end_date, "%Y%m%d").date()
        stmt = stmt.where(Announcement.ann_date <= end)

    stmt = stmt.order_by(desc(Announcement.ann_date)).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return {
        "ts_code": ts_code,
        "items": [
            {
                "id": r.id,
                "ann_date": r.ann_date.isoformat() if r.ann_date else None,
                "name": r.name,
                "title": r.title,
                "type": r.type,
                "cninfo_id": r.cninfo_id,
                "pdf_url": r.pdf_url,
                "file_path": r.file_path,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/announcements")
async def list_announcements(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """查询全市场公告（分页）"""
    stmt = select(Announcement)

    if start_date:
        start = datetime.strptime(start_date, "%Y%m%d").date()
        stmt = stmt.where(Announcement.ann_date >= start)
    if end_date:
        end = datetime.strptime(end_date, "%Y%m%d").date()
        stmt = stmt.where(Announcement.ann_date <= end)

    stmt = stmt.order_by(desc(Announcement.ann_date)).limit(limit).offset(offset)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return {
        "items": [
            {
                "ts_code": r.ts_code,
                "name": r.name,
                "ann_date": r.ann_date.isoformat() if r.ann_date else None,
                "title": r.title,
                "type": r.type,
                "cninfo_id": r.cninfo_id,
                "pdf_url": r.pdf_url,
                "file_path": r.file_path,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── 研报元数据 ───────────────────────────────────────


@router.get("/research-reports")
async def list_research_reports(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """查询研报元数据（不限个股，全局限）"""
    stmt = select(ResearchReportMeta)

    if start_date:
        start = datetime.strptime(start_date, "%Y%m%d").date()
        stmt = stmt.where(ResearchReportMeta.trade_date >= start)
    if end_date:
        end = datetime.strptime(end_date, "%Y%m%d").date()
        stmt = stmt.where(ResearchReportMeta.trade_date <= end)

    stmt = stmt.order_by(desc(ResearchReportMeta.trade_date)).limit(limit).offset(offset)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return {
        "items": [
            {
                "id": r.id,
                "trade_date": r.trade_date.isoformat() if r.trade_date else None,
                "ts_code": r.ts_code,
                "file_name": r.file_name,
                "author": r.author,
                "inst_csname": r.inst_csname,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/research-reports/{ts_code}")
async def get_research_reports_by_stock(
    ts_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """查询个股研报元数据"""
    stmt = select(ResearchReportMeta).where(ResearchReportMeta.ts_code == ts_code)

    if start_date:
        start = datetime.strptime(start_date, "%Y%m%d").date()
        stmt = stmt.where(ResearchReportMeta.trade_date >= start)
    if end_date:
        end = datetime.strptime(end_date, "%Y%m%d").date()
        stmt = stmt.where(ResearchReportMeta.trade_date <= end)

    stmt = stmt.order_by(desc(ResearchReportMeta.trade_date)).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return {
        "ts_code": ts_code,
        "items": [
            {
                "id": r.id,
                "trade_date": r.trade_date.isoformat() if r.trade_date else None,
                "file_name": r.file_name,
                "author": r.author,
                "inst_csname": r.inst_csname,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# Phase 31 D-C1：文档上传/查询/下载链路已完全移除，agent 的研报查询改走
# report_service.get_research_reports → research_report_meta 表。
# MongoDB uploaded_documents collection 保留作历史归档（D-C2），代码不再读写。
