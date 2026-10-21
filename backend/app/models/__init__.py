"""
数据模型 - 统一导出

清理说明（2026-10-21）：以下模型零引用且其表已 DROP（alembic 030），已删除：
Concept / StockConcept / ConceptLimitDetail / StockPool / ConceptScore /
StockScore。`research_report_meta` 表仍在，但只经原生 SQL 读写（无 ORM
路径），其模型一并删除；如需 ORM 访问再按实际库结构重建。
"""

from app.models.event import Event

from .models import (
    Alert,
    # 分析
    AnalysisReport,
    # 资讯
    Announcement,
    # Base
    Base,
    CompanyProfile,
    # 概念（现行：THS 体系）
    ConceptLimit,
    DailyBasic,
    DailyData,
    IndexDaily,
    IngestionCheckpoint,
    IngestionProgressEvent,
    IngestionRun,
    MonitorRule,
    PortfolioPosition,
    # 行情
    Stock,
    ThsConcept,
    ThsConceptMember,
    # Sub-Project 1: 用户与持仓
    User,
    # 用户数据
    Watchlist,
)

__all__ = [
    "Stock",
    "DailyData",
    "DailyBasic",
    "IndexDaily",
    "ThsConcept",
    "ThsConceptMember",
    "ConceptLimit",
    "Watchlist",
    "MonitorRule",
    "Alert",
    "User",
    "PortfolioPosition",
    "AnalysisReport",
    "Announcement",
    "CompanyProfile",
    "IngestionRun",
    "IngestionProgressEvent",
    "IngestionCheckpoint",
    "Event",
    "Base",
]