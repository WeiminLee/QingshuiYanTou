"""
数据接入层元数据常量

所有数据入库时必须使用以下常量定义，
确保 source_type / confidence_tier 全系统统一。
"""

from dataclasses import dataclass

# ── 当前系统支持的数据源 ────────────────────────────────

CURRENT_PARSER_VERSION = "v1.0"
CURRENT_KG_SCHEMA_VERSION = "v4"
CURRENT_KG_PARSER_VERSION = "v4"

SOURCE_INTERACTIVE_QA = "interactive_qa"  # 互动易 Q&A
SOURCE_RESEARCH_REPORT = "research_report"  # 券商研报
SOURCE_NEWS_FLASH = "news_flash"  # 新闻快讯（多来源）
SOURCE_MANUAL_UPLOAD = "manual_upload"  # 手动上传
SOURCE_TUSHARE_DAILY = "tushare_daily"  # Tushare 日线/基本面
SOURCE_TUSHARE_INDEX = "tushare_index"  # Tushare 指数
SOURCE_TUSHARE_CONCEPT = "tushare_concept"  # Tushare/THS 概念板块
SOURCE_TUSHARE_MAINBZ = "tushare_mainbz"  # Tushare 主营构成
SOURCE_CLOUD_API = "cloud_api"  # 外部云 API
SOURCE_CNINFO_ANNOUNCEMENT = "cninfo_announcement"  # 巨潮公告
SOURCE_CNINFO_DOCUMENT = "cninfo_document"  # 巨潮文档
SOURCE_THS_CONCEPT = "ths_concept"  # 同花顺概念


@dataclass
class SourceMeta:
    source_type: str
    source_name: str
    confidence_tier: str  # Tier 0-4
    confidence_min: float
    confidence_max: float
    parser_version: str  # 当前解析器版本


# source_type → 元数据映射表
SOURCE_META_MAP: dict[str, SourceMeta] = {
    SOURCE_INTERACTIVE_QA: SourceMeta(
        source_type=SOURCE_INTERACTIVE_QA,
        source_name="东方财富互动易",
        confidence_tier="Tier 1",
        confidence_min=0.75,
        confidence_max=0.90,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_RESEARCH_REPORT: SourceMeta(
        source_type=SOURCE_RESEARCH_REPORT,
        source_name="券商研报",
        confidence_tier="Tier 4",
        confidence_min=0.50,
        confidence_max=0.75,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_NEWS_FLASH: SourceMeta(
        source_type=SOURCE_NEWS_FLASH,
        source_name="新闻快讯",
        confidence_tier="Tier 4",
        confidence_min=0.50,
        confidence_max=0.75,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_MANUAL_UPLOAD: SourceMeta(
        source_type=SOURCE_MANUAL_UPLOAD,
        source_name="手动上传",
        confidence_tier="Tier 4",
        confidence_min=0.50,
        confidence_max=0.75,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    # ── Tushare 数据 ───────────────────────────────
    SOURCE_TUSHARE_DAILY: SourceMeta(
        source_type=SOURCE_TUSHARE_DAILY,
        source_name="Tushare 日线",
        confidence_tier="Tier 0",
        confidence_min=0.90,
        confidence_max=1.0,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_TUSHARE_INDEX: SourceMeta(
        source_type=SOURCE_TUSHARE_INDEX,
        source_name="Tushare 指数",
        confidence_tier="Tier 0",
        confidence_min=0.90,
        confidence_max=1.0,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_TUSHARE_CONCEPT: SourceMeta(
        source_type=SOURCE_TUSHARE_CONCEPT,
        source_name="THS 同花顺概念",
        confidence_tier="Tier 0",
        confidence_min=0.85,
        confidence_max=1.0,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_TUSHARE_MAINBZ: SourceMeta(
        source_type=SOURCE_TUSHARE_MAINBZ,
        source_name="Tushare 主营构成",
        confidence_tier="Tier 0",
        confidence_min=0.90,
        confidence_max=1.0,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_CLOUD_API: SourceMeta(
        source_type=SOURCE_CLOUD_API,
        source_name="云 API",
        confidence_tier="Tier 2",
        confidence_min=0.65,
        confidence_max=0.85,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_CNINFO_ANNOUNCEMENT: SourceMeta(
        source_type=SOURCE_CNINFO_ANNOUNCEMENT,
        source_name="巨潮资讯网",
        confidence_tier="Tier 1",
        confidence_min=0.75,
        confidence_max=0.90,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_CNINFO_DOCUMENT: SourceMeta(
        source_type=SOURCE_CNINFO_DOCUMENT,
        source_name="巨潮资讯PDF",
        confidence_tier="Tier 1",
        confidence_min=0.75,
        confidence_max=0.90,
        parser_version=CURRENT_PARSER_VERSION,
    ),
    SOURCE_THS_CONCEPT: SourceMeta(
        source_type=SOURCE_THS_CONCEPT,
        source_name="THS同花顺概念",
        confidence_tier="Tier 0",
        confidence_min=0.85,
        confidence_max=1.0,
        parser_version=CURRENT_PARSER_VERSION,
    ),
}


def get_source_meta(source_type: str) -> SourceMeta | None:
    """Return metadata for a known source type."""
    return SOURCE_META_MAP.get(source_type)
