"""LLM 抽取信号持久化模块

将 LLM 抽取结果中的信号写入 PostgreSQL signals 表。
复用 evidence_ingestion._upsert_signal_records 的 upsert 逻辑。
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.signals.models import Signal, SignalPropagation

logger = logging.getLogger(__name__)

# 有效信号类型集合
_VALID_SIGNAL_TYPES = frozenset({
    "mass_production", "capacity", "policy", "capex", "earnings", "order", "risk",
})

# 有效极性集合
_VALID_POLARITIES = frozenset({"positive", "negative", "risk"})

# 有效主体类型集合
_VALID_SUBJECT_TYPES = frozenset({"company", "product", "sector", "policy"})

# 信号类型与主体类型的对应关系
_SIGNAL_SUBJECT_MAP: dict[str, str] = {
    "mass_production": "product",
    "capacity": "sector",
    "policy": "policy",
    "capex": "sector",
    "earnings": "company",
    "order": "company",
    "risk": "company",
}

# 每个信号类型的触发词（用于校验 excerpt 是否包含相关内容）
_SIGNAL_TRIGGER_WORDS: dict[str, list[str]] = {
    "mass_production": ["量产", "批量", "交付", "达产", "试产", "投产", "规模", "产能释放"],
    "capacity": ["产能", "扩产", "投产", "新建", "扩建", "产线", "工厂", "基地"],
    "policy": ["政策", "补贴", "规划", "国产替代", "十五五", "战略", "十四五", "支持"],
    "capex": ["资本开支", "CAPEX", "设备采购", "投资", "算力", "研发投入"],
    "earnings": ["业绩", "营收", "净利润", "利润", "盈利", "亏损", "扭亏", "预增", "分红", "收益", "收入"],
    "order": ["订单", "中标", "合同", "签约", "采购", "招标", "交付", "新订单"],
    "risk": ["风险", "处罚", "诉讼", "减值", "停产", "立案", "调查", "退市", "违约", "流失", "竞争加剧"],
}

# 风险提示/免责声明关键词（post-filter：如果 excerpt 只包含这些词，拒绝）
_RISK_DISCLAIMER_KW = ["不确定性", "敬请投资者注意", "风险提示", "注意风险", "谨慎决策", "敬请投资者"]


def _is_disclaimer_only(excerpt: str) -> bool:
    """检查 excerpt 是否仅是免责声明话术，没有实质性内容"""
    # 去除免责声明关键词后，剩余内容是否太少
    cleaned = excerpt
    for kw in _RISK_DISCLAIMER_KW:
        cleaned = cleaned.replace(kw, "")
    # 也去掉通用标点和空格
    cleaned = re.sub("[，。！？、；：\"\"''（）\\s]", "", cleaned)
    # 如果去除后剩余中文字符 < 6，说明主要是免责声明
    remaining = len(re.findall(r'[一-鿿]', cleaned))
    return remaining < 6


def _validate_signal(signal: dict[str, Any]) -> str | None:
    """校验单条信号质量，返回 None 表示通过，返回字符串表示拒绝原因"""
    signal_type = str(signal.get("signal_type", ""))
    polarity = str(signal.get("polarity", ""))
    subject_name = str(signal.get("subject_name", "")).strip()
    subject_type = str(signal.get("subject_type", "")).strip()
    strength = signal.get("strength", 0)
    excerpt = str(signal.get("evidence_excerpt", "")).strip()

    # 1. 信号类型必须有效
    if signal_type not in _VALID_SIGNAL_TYPES:
        return f"无效信号类型: {signal_type}"

    # 2. 极性必须有效
    if polarity not in _VALID_POLARITIES:
        return f"无效极性: {polarity}"

    # 3. 主体名称不能为空
    if not subject_name:
        return "主体名称为空"

    # 4. 主体类型必须有效
    if subject_type not in _VALID_SUBJECT_TYPES:
        return f"无效主体类型: {subject_type}"

    # 5. 主体类型必须与信号类型匹配
    expected_type = _SIGNAL_SUBJECT_MAP.get(signal_type)
    if expected_type and subject_type != expected_type:
        return f"主体类型不匹配: {signal_type}→{subject_type}, 期望 {expected_type}"

    # 6. 强度过低，放弃
    try:
        strength_val = int(strength)
    except (ValueError, TypeError):
        strength_val = 0
    if strength_val < 20:
        return f"信号强度过低: {strength_val}"
    # risk 信号强度要求更高（避免免责声明误报）
    if signal_type == "risk" and strength_val < 30:
        return f"risk 信号强度过低: {strength_val}"

    # 7. 如果是 risk 信号，检查是否只是免责声明话术
    if signal_type == "risk" and _is_disclaimer_only(excerpt):
        return f"risk 信号仅含免责声明: {excerpt[:40]}"

    # 8. excerpt 必须包含至少一个触发词
    if signal_type in _SIGNAL_TRIGGER_WORDS:
        triggers = _SIGNAL_TRIGGER_WORDS[signal_type]
        if not any(kw in excerpt for kw in triggers):
            # 宽松校验：如果 excerpt 包含数字或百分号也通过（如"营收120亿元"）
            if not re.search(r'[\d.%]', excerpt):
                return f"excerpt 不含触发词: {excerpt[:40]}"

    # 9. excerpt 必须有实际内容（中文字符数 >= 4）
    chinese_chars = len(re.findall(r'[一-鿿]', excerpt))
    if chinese_chars < 4:
        return f"excerpt 中文内容过少: {excerpt[:40]}"

    return None  # 通过


def _llm_signal_id(evidence_id: str, signal_type: str, subject_name: str, excerpt: str) -> str:
    """为 LLM 输出的信号生成稳定 ID"""
    raw = "|".join([evidence_id, signal_type, subject_name, excerpt[:60]])
    return f"LLM:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _llm_signal_values(
    evidence: dict[str, Any],
    signal: dict[str, Any],
) -> dict[str, Any]:
    """将 LLM 输出信号转为 Signal 表 upsert 格式"""
    evidence_id = str(evidence.get("evidence_id", ""))
    source_type = str(evidence.get("source_type", "unknown"))
    source_id = str(evidence.get("source_id", evidence_id))
    source_name = str(evidence.get("source_name", ""))
    subject_hint = evidence.get("subject_hint") or {}
    ts_code = str(subject_hint.get("ts_code", ""))
    published_at = evidence.get("publish_date")
    if isinstance(published_at, str):
        try:
            # 纯日期格式 '2026-04-29'
            published_at = datetime.combine(date.fromisoformat(published_at), datetime.min.time(), tzinfo=UTC)
        except (ValueError, TypeError):
            try:
                # 完整 datetime 格式
                published_at = datetime.fromisoformat(published_at).replace(tzinfo=UTC)
            except (ValueError, TypeError):
                published_at = None
    elif isinstance(published_at, datetime) and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)

    signal_type = str(signal.get("signal_type", ""))
    subject_name = str(signal.get("subject_name", ""))
    excerpt = str(signal.get("evidence_excerpt", ""))
    signal_id = _llm_signal_id(evidence_id, signal_type, subject_name, excerpt)

    strength = int(signal.get("strength", 50))
    # LLM 置信度高于规则匹配，默认 0.85
    confidence = Decimal(str(round(signal.get("confidence", 0.85), 3)))
    value_score = min(100, int(strength * 0.7 + 20))

    return {
        "signal_id": signal_id,
        "source_type": source_type + ":llm",
        "source_id": source_id,
        "source_title": source_name,
        "source_url": None,
        "published_at": published_at,
        "detected_at": datetime.now(UTC),
        "subject_name": subject_name,
        "subject_type": str(signal.get("subject_type", "company")),
        "signal_type": signal_type,
        "polarity": str(signal.get("polarity", "positive")),
        "strength": strength,
        "confidence": confidence,
        "freshness_score": 100,
        "value_score": value_score,
        "summary": str(signal.get("summary", ""))[:160],
        "evidence_excerpt": excerpt[:240],
        "status": "new",
        "metadata_": {
            "evidence_id": evidence_id,
            "ts_code": ts_code,
            "source": "llm_extraction",
        },
    }


async def persist_llm_signals(
    session: AsyncSession,
    evidence: dict[str, Any],
    signals: list[dict[str, Any]],
) -> dict[str, int]:
    """将 LLM 抽取的信号写入 PostgreSQL signals 表。

    Args:
        session: 数据库会话
        evidence: 证据文档
        signals: LLM 抽取的信号列表，每个元素格式：
            {signal_type, polarity, strength, subject_name, subject_type, summary, evidence_excerpt}

    Returns:
        {"signals_upserted": int, "signals_filtered": int}
    """
    if not signals:
        return {"signals_upserted": 0, "signals_filtered": 0}

    signals_upserted = 0
    signals_filtered = 0
    for signal in signals:
        # 后处理校验
        reason = _validate_signal(signal)
        if reason:
            logger.debug("LLM 信号过滤: %s — %s", signal.get("signal_type", "?"), reason)
            signals_filtered += 1
            continue

        values = _llm_signal_values(evidence, signal)
        stmt = insert(Signal).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["signal_id"],
            set_={
                "detected_at": values["detected_at"],
                "freshness_score": values["freshness_score"],
                "value_score": values["value_score"],
                "summary": values["summary"],
                "evidence_excerpt": values["evidence_excerpt"],
                "metadata": values["metadata_"],
            },
        )
        await session.execute(stmt)
        signals_upserted += 1

    if signals_filtered:
        logger.info("LLM 信号: %d 写入, %d 被过滤", signals_upserted, signals_filtered)

    return {"signals_upserted": signals_upserted, "signals_filtered": signals_filtered}