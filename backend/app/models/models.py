"""
数据库模型 - SQLAlchemy ORM

所有表与 alembic/versions/ 下的迁移保持一致。
Base 统一从 app.core.database 导入，确保 alembic 与运行时使用同一个 Base 实例。
"""
from datetime import date, datetime
from typing import Any, Optional
from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey,
    Index, Integer, Numeric, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy import BigInteger, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base  # 统一 Base，与 alembic 共享


# ── 1. 行情层 ────────────────────────────────────────────────────────────────

class Stock(Base):
    """股票基本信息"""
    __tablename__ = "stocks"

    ts_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    area: Mapped[Optional[str]] = mapped_column(String(50))
    industry: Mapped[Optional[str]] = mapped_column(String(50))
    market: Mapped[Optional[str]] = mapped_column(String(20))
    list_date: Mapped[Optional[date]] = mapped_column(Date)
    is_hs: Mapped[Optional[str]] = mapped_column(String(1))


class DailyData(Base):
    """日线行情"""
    __tablename__ = "daily_data"
    __table_args__ = (
        Index("idx_daily_ts_date", "ts_code", "trade_date", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), ForeignKey("stocks.ts_code"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Optional[float]] = mapped_column(Float)
    high: Mapped[Optional[float]] = mapped_column(Float)
    low: Mapped[Optional[float]] = mapped_column(Float)
    close: Mapped[Optional[float]] = mapped_column(Float)
    pre_close: Mapped[Optional[float]] = mapped_column(Float)
    change: Mapped[Optional[float]] = mapped_column(Float)
    pct_chg: Mapped[Optional[float]] = mapped_column(Float)
    vol: Mapped[Optional[float]] = mapped_column(Float)
    amount: Mapped[Optional[float]] = mapped_column(Float)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)


class DailyBasic(Base):
    """每日基本面指标（PE/PB/换手率/市值等）"""
    __tablename__ = "daily_basic"
    __table_args__ = (
        Index("idx_daily_basic_ts_date", "ts_code", "trade_date", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[Optional[float]] = mapped_column(Float)
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float)           # 换手率(%)
    turnover_rate_f: Mapped[Optional[float]] = mapped_column(Float)        # 自由流通股换手率(%)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float)           # 量比
    pe: Mapped[Optional[float]] = mapped_column(Float)                     # 市盈率
    pe_ttm: Mapped[Optional[float]] = mapped_column(Float)                # 滚动市盈率
    pb: Mapped[Optional[float]] = mapped_column(Float)                   # 市净率
    ps: Mapped[Optional[float]] = mapped_column(Float)                    # 市销率
    ps_ttm: Mapped[Optional[float]] = mapped_column(Float)                # 滚动市销率
    dv_ratio: Mapped[Optional[float]] = mapped_column(Float)              # 股息率(%)
    dv_ttm: Mapped[Optional[float]] = mapped_column(Float)                # 滚动股息率(%)
    total_share: Mapped[Optional[float]] = mapped_column(Float)            # 总股本(万股)
    float_share: Mapped[Optional[float]] = mapped_column(Float)            # 流通股本(万股)
    free_share: Mapped[Optional[float]] = mapped_column(Float)            # 自由流通股本(万股)
    total_mv: Mapped[Optional[float]] = mapped_column(Float)              # 总市值(万元)
    circ_mv: Mapped[Optional[float]] = mapped_column(Float)               # 流通市值(万元)


class IndexDaily(Base):
    """指数日线（HS300 等）"""
    __tablename__ = "index_daily"
    __table_args__ = (
        Index("idx_index_daily_ts_date", "ts_code", "trade_date", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Optional[float]] = mapped_column(Float)
    high: Mapped[Optional[float]] = mapped_column(Float)
    low: Mapped[Optional[float]] = mapped_column(Float)
    close: Mapped[Optional[float]] = mapped_column(Float)
    pre_close: Mapped[Optional[float]] = mapped_column(Float)
    change: Mapped[Optional[float]] = mapped_column(Float)
    pct_chg: Mapped[Optional[float]] = mapped_column(Float)
    vol: Mapped[Optional[float]] = mapped_column(Float)
    amount: Mapped[Optional[float]] = mapped_column(Float)


# ── 2. 概念层 ────────────────────────────────────────────────────────────────

class Concept(Base):
    """概念板块（通用，来源不限）"""
    __tablename__ = "concepts"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    src: Mapped[Optional[str]] = mapped_column(String(20))


class StockConcept(Base):
    """个股-概念映射（通用）"""
    __tablename__ = "stock_concepts"
    __table_args__ = (
        UniqueConstraint("ts_code", "concept_code", name="idx_stock_concepts_unique"),
        Index("idx_stock_concepts_concept", "concept_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    concept_code: Mapped[str] = mapped_column(String(20), nullable=False)


class ThsConcept(Base):
    """THS 同花顺概念板块（TI 格式，与 limit_cpt_list 体系一致）"""
    __tablename__ = "ths_concepts"

    ts_code: Mapped[str] = mapped_column(String(20), primary_key=True)   # 如 885806.TI
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    count: Mapped[Optional[int]] = mapped_column(Integer)
    exchange: Mapped[Optional[str]] = mapped_column(String(10))          # A/N/E
    list_date: Mapped[Optional[date]] = mapped_column(Date)
    type: Mapped[Optional[str]] = mapped_column(String(10))             # N/E


class ThsConceptMember(Base):
    """THS 概念-成分股映射"""
    __tablename__ = "ths_concept_members"
    __table_args__ = (
        UniqueConstraint("ts_code", "con_code", name="idx_ths_member_unique"),
        Index("idx_ths_member_concept", "ts_code"),
        Index("idx_ths_member_stock", "con_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)    # THS 概念代码
    con_code: Mapped[str] = mapped_column(String(20), nullable=False)    # 成分股代码
    con_name: Mapped[Optional[str]] = mapped_column(String(50))
    in_date: Mapped[Optional[date]] = mapped_column(Date)


class ConceptLimit(Base):
    """涨停概念每日汇总"""
    __tablename__ = "concept_limit"
    __table_args__ = (
        UniqueConstraint("concept_code", "trade_date", name="idx_concept_limit_unique"),
        Index("idx_concept_limit_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_code: Mapped[str] = mapped_column(String(20), nullable=False)
    concept_name: Mapped[str] = mapped_column(String(100), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[Optional[int]] = mapped_column(Integer)                # 连板天数
    up_stat: Mapped[Optional[str]] = mapped_column(String(50))
    cons_nums: Mapped[Optional[int]] = mapped_column(Integer)            # 成分股数
    up_nums: Mapped[Optional[int]] = mapped_column(Integer)             # 涨停股票数
    pct_chg: Mapped[Optional[float]] = mapped_column(Float)
    rank: Mapped[Optional[int]] = mapped_column(Integer)


class ConceptLimitDetail(Base):
    """涨停概念内个股明细"""
    __tablename__ = "concept_limit_detail"
    __table_args__ = (
        UniqueConstraint("concept_code", "ts_code", "trade_date", name="idx_concept_limit_detail_unique"),
        Index("idx_concept_limit_detail_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_code: Mapped[str] = mapped_column(String(20), nullable=False)
    concept_name: Mapped[str] = mapped_column(String(100), nullable=False)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[Optional[str]] = mapped_column(String(50))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)


# ── 3. 用户数据层 ─────────────────────────────────────────────────────────────

class Watchlist(Base):
    """自选股"""
    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("ts_code", name="idx_watchlist_ts_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), ForeignKey("stocks.ts_code"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    note: Mapped[Optional[str]] = mapped_column(String(200))


class MonitorRule(Base):
    """监控规则"""
    __tablename__ = "monitor_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Alert(Base):
    """告警记录"""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


# ── 4. 分析层 ────────────────────────────────────────────────────────────────

class AnalysisReport(Base):
    """Agent 分析报告"""
    __tablename__ = "analysis_reports"
    __table_args__ = (
        Index("idx_report_ts_created", "ts_code", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    report_content: Mapped[str] = mapped_column(Text, nullable=False)
    trend: Mapped[Optional[str]] = mapped_column(String(20))
    score: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── 5. 资讯层 ────────────────────────────────────────────────────────────────

class Announcement(Base):
    """巨潮资讯公告（含元数据字段）"""
    __tablename__ = "announcements"
    __table_args__ = (
        Index("idx_ann_unique_key", "ts_code", "ann_date", "title", unique=True),
        Index("idx_ann_ts_date", "ts_code", "ann_date"),
        Index("idx_ann_date", "ann_date"),
        Index("idx_ann_cninfo_id", "cninfo_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    title: Mapped[Optional[str]] = mapped_column(Text)
    type: Mapped[Optional[str]] = mapped_column(Text)
    # 巨潮扩展字段
    cninfo_id: Mapped[Optional[str]] = mapped_column(String(100))
    org_id: Mapped[Optional[str]] = mapped_column(String(50))
    announcement_type: Mapped[Optional[str]] = mapped_column(Text)
    pdf_url: Mapped[Optional[str]] = mapped_column(Text)
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    # 数据接入层元数据
    source_type: Mapped[str] = mapped_column(String(50), server_default="cninfo_announcement")
    source_name: Mapped[str] = mapped_column(String(100), server_default="巨潮资讯网")
    confidence_tier: Mapped[str] = mapped_column(String(20), server_default="Tier 1")
    parser_version: Mapped[str] = mapped_column(String(20), server_default="v1.0")
    extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class ResearchReportMeta(Base):
    """研报元数据（含元数据字段）"""
    __tablename__ = "research_report_meta"
    __table_args__ = (
        UniqueConstraint("trade_date", "file_name", name="idx_rmeta_unique"),
        Index("idx_rmeta_ts_date", "ts_code", "trade_date"),
        Index("idx_rmeta_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    ts_code: Mapped[Optional[str]] = mapped_column(String(20))
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(200))
    inst_csname: Mapped[Optional[str]] = mapped_column(String(200))
    # 数据接入层元数据
    source_type: Mapped[str] = mapped_column(String(50), server_default="research_report")
    source_name: Mapped[str] = mapped_column(String(100), server_default="Tushare研报")
    confidence_tier: Mapped[str] = mapped_column(String(20), server_default="Tier 4")
    parser_version: Mapped[str] = mapped_column(String(20), server_default="v1.0")
    extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class DownloadedDocument(Base):
    """
    已下载文档记录（防重 + 断点续传）

    用于：
    - 公告 PDF 下载防重
    - 调研公告、业绩说明会记录等下载防重
    - 进程中断后继续时跳过已下载文件
    """
    __tablename__ = "downloaded_documents"
    __table_args__ = (
        UniqueConstraint("cninfo_id", name="idx_doc_cninfo_id_unique"),
        Index("idx_doc_ts_date", "ts_code", "doc_date"),
        Index("idx_doc_downloaded_at", "downloaded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 标识
    cninfo_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # 文件信息
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)  # 见文档类型常量
    doc_date: Mapped[date] = mapped_column(Date, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer)  # bytes
    # 巨潮原始字段（便于溯源）
    org_id: Mapped[Optional[str]] = mapped_column(String(50))
    pdf_url: Mapped[Optional[str]] = mapped_column(Text)
    # 元数据
    source_type: Mapped[str] = mapped_column(String(30), server_default="cninfo_document")
    source_name: Mapped[str] = mapped_column(String(50), server_default="巨潮资讯PDF")
    confidence_tier: Mapped[str] = mapped_column(String(10), server_default="Tier 1")
    parser_version: Mapped[str] = mapped_column(String(10), server_default="v1.0")
    extracted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    downloaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── 6. 业务层 ────────────────────────────────────────────────────────────────

class StockPool(Base):
    """调研池（每日收盘后更新热门板块纳入的股票）"""
    __tablename__ = "stock_pool"
    __table_args__ = (
        Index("idx_pool_in_date", "in_date"),
    )

    ts_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    concept_code: Mapped[Optional[str]] = mapped_column(String(20))
    concept_name: Mapped[Optional[str]] = mapped_column(String(100))
    in_date: Mapped[date] = mapped_column(Date, nullable=False)
    out_date: Mapped[Optional[date]] = mapped_column(Date)
    pct_chg_5d: Mapped[Optional[float]] = mapped_column(Numeric(8, 2))
    score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    # 元数据
    source_type: Mapped[str] = mapped_column(String(30), server_default="ths_concept")
    source_name: Mapped[str] = mapped_column(String(50), server_default="THS同花顺概念")
    confidence_tier: Mapped[str] = mapped_column(String(10), server_default="Tier 0")
    parser_version: Mapped[str] = mapped_column(String(10), server_default="v1.0")
    extracted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CompanyProfile(Base):
    """公司概况（Tushare stock_company）"""
    __tablename__ = "company_profiles"

    ts_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    com_name: Mapped[Optional[str]] = mapped_column(String(200))
    com_id: Mapped[Optional[str]] = mapped_column(String(50))
    chairman: Mapped[Optional[str]] = mapped_column(String(100))
    manager: Mapped[Optional[str]] = mapped_column(String(100))
    secretary: Mapped[Optional[str]] = mapped_column(String(100))
    reg_capital: Mapped[Optional[str]] = mapped_column(String(100))
    setup_date: Mapped[Optional[str]] = mapped_column(String(50))
    province: Mapped[Optional[str]] = mapped_column(String(50))
    city: Mapped[Optional[str]] = mapped_column(String(50))
    introduction: Mapped[Optional[str]] = mapped_column(Text)
    website: Mapped[Optional[str]] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    office: Mapped[Optional[str]] = mapped_column(Text)
    business_scope: Mapped[Optional[str]] = mapped_column(Text)
    employees: Mapped[Optional[int]] = mapped_column(Integer)
    main_business: Mapped[Optional[str]] = mapped_column(Text)
    exchange: Mapped[Optional[str]] = mapped_column(String(10))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ── 7. 评分层 ────────────────────────────────────────────────────────────────

class ConceptScore(Base):
    """概念每日评分"""
    __tablename__ = "concept_scores"
    __table_args__ = (
        UniqueConstraint("concept_ts_code", "trade_date", name="uq_concept_score_ts_date"),
        Index("idx_concept_score_trade_date", "trade_date"),
        Index("idx_concept_score_score", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    score: Mapped[Optional[float]] = mapped_column(Float)
    momentum_5d: Mapped[Optional[float]] = mapped_column(Float)
    momentum_1d: Mapped[Optional[float]] = mapped_column(Float)
    breadth: Mapped[Optional[float]] = mapped_column(Float)
    breadth_rising: Mapped[Optional[int]] = mapped_column(Integer)
    breadth_total: Mapped[Optional[int]] = mapped_column(Integer)
    relative_strength: Mapped[Optional[float]] = mapped_column(Float)
    stock_count: Mapped[Optional[int]] = mapped_column(Integer)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StockScore(Base):
    """个股每日评分"""
    __tablename__ = "stock_scores"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_stock_score_ts_date"),
        Index("idx_stock_score_trade_date", "trade_date"),
        Index("idx_stock_score_total", "total_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(50))
    total_score: Mapped[Optional[float]] = mapped_column(Float)
    momentum_score: Mapped[Optional[float]] = mapped_column(Float)
    trend_score: Mapped[Optional[float]] = mapped_column(Float)
    capital_score: Mapped[Optional[float]] = mapped_column(Float)
    concept_bonus: Mapped[Optional[float]] = mapped_column(Float)
    valuation_bonus: Mapped[Optional[float]] = mapped_column(Float)
    momentum_5d: Mapped[Optional[float]] = mapped_column(Float)
    turnover_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    vol_ratio: Mapped[Optional[float]] = mapped_column(Float)
    ma_state: Mapped[Optional[str]] = mapped_column(String(20))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── 8. 知识图谱层 ────────────────────────────────────────────────────────────
# kg_entities / kg_relationships 已迁移至 Neo4j（2026-04-08）
# 参见 app/knowledge/entity_service.py / relation_service.py


    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sync_type: Mapped[str] = mapped_column(String(20), nullable=False)  # daily_cron / manual
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime)   # 上次同步时间戳
    records_synced: Mapped[int] = mapped_column(Integer, default=0)       # 本次同步记录数
    announcement_count: Mapped[int] = mapped_column(Integer, default=0)   # 公告数
    report_count: Mapped[int] = mapped_column(Integer, default=0)         # 研报数
    status: Mapped[str] = mapped_column(String(20), default="success")    # success / failed
    info: Mapped[Optional[str]] = mapped_column(Text)                    # 附加信息
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EvalRun(Base):
    """评估运行记录（每次 AnalysisReport 生成记一条，ADV-DATA-02）"""
    __tablename__ = "eval_runs"
    __table_args__ = (
        UniqueConstraint("report_id", name="uq_eval_runs_report_id"),
        Index("idx_eval_runs_report_id", "report_id"),
        Index("idx_eval_runs_run_type", "run_type"),
        Index("idx_eval_runs_run_at", "run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=True,
    )
    ts_code: Mapped[Optional[str]] = mapped_column(String(20))
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    run_type: Mapped[str] = mapped_column(
        String(50), server_default="automated_daily",
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )
    recall_score: Mapped[Optional[float]] = mapped_column(Float)
    coverage_score: Mapped[Optional[float]] = mapped_column(Float)
    entity_count: Mapped[Optional[int]] = mapped_column(Integer)
    confidence_avg: Mapped[Optional[float]] = mapped_column(Float)
    analyst_id: Mapped[Optional[str]] = mapped_column(String(50))
    sample_size: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[dict]] = mapped_column(JSON)
    experiment_group: Mapped[Optional[str]] = mapped_column(String(50))
    variant: Mapped[Optional[str]] = mapped_column(String(50))
    source_type: Mapped[str] = mapped_column(String(50), server_default="research_report")
    confidence_tier: Mapped[str] = mapped_column(String(20), server_default="Tier 4")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )


class BackfillCheckpoint(Base):
    """回填进度记录（支持断点续传）"""
    __tablename__ = "backfill_checkpoint"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)   # P0 / P1 / P2
    cursor_token: Mapped[Optional[str]] = mapped_column(Text)          # fetch 的 next_cursor
    last_ann_id: Mapped[Optional[str]] = mapped_column(String(100))   # 最后处理的 ann_id
    synced_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="in_progress"
    )  # in_progress / done / failed
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


# ── 9. 日志审计层 ────────────────────────────────────────────────────────────

class LogEntry(Base):
    """
    结构化日志表 - 用于跟踪数据接入层和推理服务的日志情况

    字段说明:
    - level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - service: 服务名称 (data_pipeline, reasoning)
    - module: 模块名称 (fetcher, scheduler, agent, tool_executor 等)
    - trace_id: 请求追踪 ID (用于关联整个请求链路)
    - task_id: 任务 ID (用于关联特定任务)
    - duration_ms: 执行耗时 (毫秒)
    - extra_data: 额外元数据 (JSONB 格式存储)
    """
    __tablename__ = "logs"
    __table_args__ = (
        Index("idx_logs_timestamp", "timestamp"),
        Index("idx_logs_level", "level"),
        Index("idx_logs_service", "service"),
        Index("idx_logs_trace_id", "trace_id"),
        Index("idx_logs_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── 10. 数据接入进度与断点 ────────────────────────────────────────────────

class IngestionRun(Base):
    """一次数据接入任务运行记录。"""
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_ingestion_runs_run_id"),
        Index("idx_ingestion_runs_source_scope", "source", "scope"),
        Index("idx_ingestion_runs_status", "status"),
        Index("idx_ingestion_runs_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False, server_default="default")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    from_watermark: Mapped[Optional[str]] = mapped_column(String(50))
    to_watermark: Mapped[Optional[str]] = mapped_column(String(50))
    current_watermark: Mapped[Optional[str]] = mapped_column(String(50))
    current_page: Mapped[Optional[int]] = mapped_column(Integer)
    total_pages: Mapped[Optional[int]] = mapped_column(Integer)
    total_items: Mapped[int] = mapped_column(Integer, server_default="0")
    processed_items: Mapped[int] = mapped_column(Integer, server_default="0")
    success_count: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, server_default="0")
    downloaded_count: Mapped[int] = mapped_column(Integer, server_default="0")
    fail_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_item_id: Mapped[Optional[str]] = mapped_column(String(100))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON)


class IngestionProgressEvent(Base):
    """数据接入任务进度事件。"""
    __tablename__ = "ingestion_progress_events"
    __table_args__ = (
        Index("idx_ingestion_events_run_id", "run_id"),
        Index("idx_ingestion_events_source_scope", "source", "scope"),
        Index("idx_ingestion_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False, server_default="default")
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    current_page: Mapped[Optional[int]] = mapped_column(Integer)
    total_pages: Mapped[Optional[int]] = mapped_column(Integer)
    total_items: Mapped[Optional[int]] = mapped_column(Integer)
    processed_items: Mapped[Optional[int]] = mapped_column(Integer)
    success_count: Mapped[Optional[int]] = mapped_column(Integer)
    skipped_count: Mapped[Optional[int]] = mapped_column(Integer)
    downloaded_count: Mapped[Optional[int]] = mapped_column(Integer)
    fail_count: Mapped[Optional[int]] = mapped_column(Integer)
    item_id: Mapped[Optional[str]] = mapped_column(String(100))
    item_title: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionCheckpoint(Base):
    """数据接入断点水位。"""
    __tablename__ = "ingestion_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "task_name",
            "scope",
            name="uq_ingestion_checkpoints_source_scope",
        ),
        Index("idx_ingestion_checkpoints_source", "source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False, server_default="default")
    watermark_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="date")
    last_success_watermark: Mapped[Optional[str]] = mapped_column(String(50))
    last_attempt_watermark: Mapped[Optional[str]] = mapped_column(String(50))
    last_run_id: Mapped[Optional[Any]] = mapped_column(UUID(as_uuid=True))
    last_status: Mapped[Optional[str]] = mapped_column(String(20))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_from_watermark: Mapped[Optional[str]] = mapped_column(String(50))
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
