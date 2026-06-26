"""
置信度体系

定义数据源置信度等级和配置。
"""

from dataclasses import dataclass
from enum import IntEnum


class ConfidenceTier(IntEnum):
    """置信度等级（数值越高越可信）"""

    TIER4_MEDIA = 1  # 自媒体/无来源
    TIER3_NEWS = 2  # 新闻/产业链资讯
    TIER2_ANALYSIS = 3  # 研报/分析师报告
    TIER1_OFFICIAL = 4  # 互动易Q&A/公告/调研纪要
    TIER0_LEGAL = 5  # 年报/招股书（法律效力，最可信）


@dataclass
class SourceConfig:
    """数据源配置"""

    source_type: str  # 来源标识
    tier: ConfidenceTier  # 置信度等级
    weight: float  # 基础置信度分值（0-1）
    description: str  # 来源说明
    examples: list[str]  # 典型示例


# 完整数据源配置表
SOURCE_CONFIG: dict[str, SourceConfig] = {
    # ── Tier 0：法律文件（最高置信度）────────────────────────────────
    "annual_report": SourceConfig(
        source_type="annual_report",
        tier=ConfidenceTier.TIER0_LEGAL,
        weight=0.95,
        description="上市公司年度报告（具有法律效力）",
        examples=["2024年年度报告", "年报"],
    ),
    "招股书": SourceConfig(
        source_type="招股书",
        tier=ConfidenceTier.TIER0_LEGAL,
        weight=0.93,
        description="IPO招股说明书（具有法律效力）",
        examples=["科创板招股书", "IPO招股书"],
    ),
    " prospectus": SourceConfig(
        source_type="prospectus",
        tier=ConfidenceTier.TIER0_LEGAL,
        weight=0.93,
        description="海外上市公司招股书",
        examples=["F-1招股书", "港股招股书"],
    ),
    # ── Tier 1：官方信息披露 ─────────────────────────────────────────
    "announcement": SourceConfig(
        source_type="announcement",
        tier=ConfidenceTier.TIER1_OFFICIAL,
        weight=0.85,
        description="交易所官方公告（具有监管效力）",
        examples=["关于签订重大合同的公告", "业绩预告"],
    ),
    "interactive_qa": SourceConfig(
        source_type="interactive_qa",
        tier=ConfidenceTier.TIER1_OFFICIAL,
        weight=0.78,
        description="互动易投资者问答（公司官方回复）",
        examples=["互动易Q&A", "投资者关系平台"],
    ),
    "调研纪要": SourceConfig(
        source_type="调研纪要",
        tier=ConfidenceTier.TIER1_OFFICIAL,
        weight=0.80,
        description="机构调研纪要（公司管理层直接交流）",
        examples=["特定对象调研", "业绩说明会纪要"],
    ),
    # ── Tier 2：分析报告 ─────────────────────────────────────────────
    "research_report": SourceConfig(
        source_type="research_report",
        tier=ConfidenceTier.TIER2_ANALYSIS,
        weight=0.72,
        description="券商研报/行业研究报告",
        examples=["中信证券研报", "光通信行业深度报告"],
    ),
    "uploaded_doc": SourceConfig(
        source_type="uploaded_doc",
        tier=ConfidenceTier.TIER2_ANALYSIS,
        weight=0.70,
        description="用户上传的研报/分析文档",
        examples=["用户上传PDF", "自选研报"],
    ),
    # ── Tier 3：新闻资讯 ─────────────────────────────────────────────
    "news_flash": SourceConfig(
        source_type="news_flash",
        tier=ConfidenceTier.TIER3_NEWS,
        weight=0.55,
        description="财联社/同花顺等实时资讯",
        examples=["财联社电报", "同花顺快讯"],
    ),
    "industry_news": SourceConfig(
        source_type="industry_news",
        tier=ConfidenceTier.TIER3_NEWS,
        weight=0.50,
        description="产业链垂直媒体/行业新闻",
        examples=["光通讯网", "半导体行业观察"],
    ),
    "cls_news": SourceConfig(
        source_type="cls_news",
        tier=ConfidenceTier.TIER3_NEWS,
        weight=0.52,
        description="财联社电报新闻",
        examples=["财联社快讯", "CLS News"],
    ),
    # ── Tier 4：自媒体 ─────────────────────────────────────────────
    "social_media": SourceConfig(
        source_type="social_media",
        tier=ConfidenceTier.TIER4_MEDIA,
        weight=0.30,
        description="自媒体/社交媒体",
        examples=["微博", "公众号"],
    ),
}


def _source_confidence(source_type: str) -> tuple[float, ConfidenceTier]:
    """
    根据 source_type 返回 (权重, 置信度等级)。

    找不到时返回 (0.4, ConfidenceTier.TIER4_MEDIA)。
    """
    config = SOURCE_CONFIG.get(source_type)
    if config:
        return config.weight, config.tier
    return 0.4, ConfidenceTier.TIER4_MEDIA
