"""入库前的研究推导。

新闻、资讯、事件（含公告和 IRM 语料）只有推出了新的一层，才写 signals。
表面句先写下来再丢掉。模型失败、对不上原文、没有新层，都是零条，不退回关键词。
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.signals.event_sources import resolve_event_origin
from app.signals.extractor import SignalCandidate, SourcePayload

logger = logging.getLogger(__name__)

ResearchLLM = Callable[[str], Awaitable[str]]

# 这些语料的 signal 任务必须走推导。行情、上传、年报、研报仍走规则抽取。
RESEARCH_EVIDENCE_SOURCE_TYPES = frozenset(
    {
        "announcement",
        "cninfo_announcement",
        "公告",
        "irm",
        "interactive_qa",
        "互动易",
        "news",
        "news_flash",
        "event",
        "cls",
        "cailian",
        "cailianshe",
        "财联社",
        "tushare",
        "eastmoney_flash",
        "eastmoney",
        "东财",
        "pboc",
        "pbc",
        "央行",
        "央行政策",
        "bloomberg",
        "彭博",
        "彭博社",
    }
)

_SIGNAL_TYPES = frozenset(
    {"policy", "order", "earnings", "capacity", "capex", "mass_production", "risk"}
)
_POLARITIES = frozenset({"positive", "negative", "risk"})
_SUBJECT_TYPES = frozenset({"sector", "company", "policy", "product"})
_BANNED_SUBJECTS = frozenset({"政策主题", "风险事件", "公司", "上市公司"})
# 这些词不是落地形式。订单交付、调研、泛泛的「政策/利好」不能当成一条通道。
_NOT_A_FORM = frozenset(
    {
        "订单",
        "订单交付",
        "调研",
        "关注",
        "问询",
        "利好",
        "利空",
        "政策",
        "风险",
        "项目开工",
        "业绩",
        "涨停",
        "跌停",
        "举措",
        "措施",
        "消息",
        "快讯",
        "新闻",
        "事件",
        "影响",
        "变化",
        "预期",
        "超预期",
        "业务布局",
        "商业化",
        "业务拓展",
        "商业化进程",
    }
)
# 结果词不是落地形式。北证50ETF、开放搜索与抓取接口这种具名通道才是。
_RESULT_FORM_RE = re.compile(
    r"(?:盈利|销售|营收|利润|收入|业绩|经营|需求)(?:改善|增长|提升|下降|增强|降低|优化|弹性|增量|布局)"
)
_SHIFT_RE = re.compile(r"从.{2,24}(?:向|到|变成|转为|改成).{2,24}")
_PRIOR_SIDE_RE = re.compile(r"从(.{2,24}?)(?:向|到|变成|转为|改成)")
# 通道变化的自然表述。只认「从 A 向 B」会把「锁定为收入确认通道」「迁移承接」
# 这类正确句子误杀（2026-10-27 抽样：summary_no_shift 占拒绝原因第一位）。
_CHANNEL_MARKERS = (
    "通道",
    "入口",
    "门槛",
    "注入",
    "承接",
    "迁移",
    "打通",
    "锁定为",
    "承载主体",
    "收入确认",
    "融资",
    "资本金",
    "股东结构",
    "业务主体",
    "产能",
    "扩产",
)
_ELLIPSIS_RE = re.compile(r"(?:\.{2,}|…+)")
# 只这些原因再给一稿。旧状态编造、形式不在原文里，重写也不会变真；
# 形式只取标题、摘录用省略号拼接、摘录没带上形式，都属于可通过重写修正的格式问题。
_RETRY_REASONS = frozenset(
    {
        "form_not_in_summary",
        "summary_no_shift",
        "form_not_specific",
        "form_only_in_title",
        "excerpt_missing_form",
        "excerpt_not_in_source",
        "excerpt_not_contiguous",
    }
)
_RETRY_REASON_TEXT = {
    "form_not_in_summary": "落地形式没有原样出现在摘要里；summary 必须以 landing_form 原文开头",
    "summary_no_shift": (
        "摘要没有写出通道变化；summary 必须出现通道/入口/门槛/注入/承接/迁移/打通/"
        "锁定为/承载主体/收入确认/融资/资本金/股东结构/业务主体/产能/扩产 之一"
    ),
    "form_not_specific": "落地形式太泛或太长；必须从正文复制 4-40 字的具体名称",
    "form_only_in_title": "落地形式只出现在标题里；必须从正文复制",
    "excerpt_missing_form": "证据摘录没有包含落地形式原文",
    "excerpt_not_in_source": "证据摘录不是正文里的连续原文",
    "excerpt_not_contiguous": "证据摘录用省略号拼接了多段；只能取包含落地形式的一段连续原文",
}
_BOARD_TERMS = (
    "北交所",
    "新三板",
    "证监会",
    "央行",
    "科创板",
    "创业板",
    "上交所",
    "深交所",
    "北证50",
    "沪深300",
    "中证500",
    "国务院",
    "发改委",
    "工信部",
    "美联储",
    "港交所",
    "彭博",
)
_TAPE_RE = re.compile(
    r"涨停|跌停|跌超|涨超|封板|炸板|(?:上证|深成|创业板|科创|北证|沪指|指数)[^。]{0,6}(?:上涨|下跌|涨|跌)"
)
# 有机制或公司行为时，即使夹了涨跌，也要进推导。纯行情才短路。
_RESEARCH_CUES = (
    "推出",
    "ETF",
    "政策",
    "基金",
    "配售",
    "分层",
    "设立",
    "获批",
    "落地",
    "试点",
    "印发",
    "征求意见",
    "办法",
    "条例",
    "净利润",
    "营收",
    "业绩",
    "订单",
    "中标",
    "合同",
    "回购",
    "减持",
    "增持",
    "立案",
    "处罚",
    "重组",
    "收购",
    "产能",
    "量产",
)
_ORG_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}(?:公司|集团|银行|证券|基金|科技|股份)")
_MAX_SIGNALS = 4
_CONTENT_CLIP = 6000


def empty_derivation_stats() -> dict[str, int]:
    return {
        "skipped_tape": 0,
        "derived": 0,
        "rejected_ungrounded": 0,
        "derivation_failed": 0,
        "no_new_layer": 0,
    }


@dataclass
class DerivationOutcome:
    candidates: list[SignalCandidate] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=empty_derivation_stats)
    rejected: list[str] = field(default_factory=list)


def evidence_needs_research(source_type: str | None) -> bool:
    raw = (source_type or "").strip()
    return raw in RESEARCH_EVIDENCE_SOURCE_TYPES or raw.lower() in RESEARCH_EVIDENCE_SOURCE_TYPES


def source_text(payload: SourcePayload) -> str:
    return "\n".join(part for part in (payload.title, payload.summary, payload.content) if part)


def _compact(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def _contains_span(haystack: str, needle: str) -> bool:
    """空白不参与对照，字序必须连续出现在原文里。"""
    needle_c = _compact(needle)
    if len(needle_c) < 2:
        return False
    return needle_c in _compact(haystack)


def is_price_tape(text: str) -> bool:
    """纯行情涨跌没有新的一层。夹了机制或公司行为的，仍要推导。"""
    if not text or not _TAPE_RE.search(text):
        return False
    return not any(cue in text for cue in _RESEARCH_CUES)


def watermark_terms(text: str) -> list[str]:
    terms: list[str] = [name for name in _BOARD_TERMS if name in text]
    for match in _ORG_RE.finditer(text or ""):
        term = match.group(0)
        if term not in terms:
            terms.append(term)
    return terms[:8]


def llm_source_type(source_type: str) -> str:
    if source_type.endswith(":llm"):
        return source_type
    return f"{source_type}:llm"


def _clip(text: str, limit: int = _CONTENT_CLIP) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def build_research_prompt(payload: SourcePayload, prior_lines: list[str]) -> str:
    watermark = "\n".join(f"- {line}" for line in prior_lines) if prior_lines else "- （无）"
    body = _clip("\n".join(part for part in (payload.summary, payload.content) if part))
    return f"""你在做入库前的研究推导。先写下表面句，再删掉它。summary 只留删句之后、相对已有水位是新的一层。

材料标题：
{payload.title or ""}

材料正文：
{body}

已有水位（本库已有的 signal，同一句不要再写）：
{watermark}

没有新的一层是合格结果：new_layer 设为 false，signals 设为空数组。不要为了产出而编一句。
行情涨跌、调研问询、标题复述，都不是新的一层。
落地形式必须是材料正文里点名的制度、产品、接口、规则、工具或合同/协议名称，4-40 个字，而且是正文里的连续片段。不能取标题；不能是业绩结果（盈利/销售/营收/利润/收入/业绩/经营/需求 + 改善/增长/提升/下降/增强/降低/优化）；不能只写「增资」「投资」「协议」这类泛词，必须带具体主体、项目或文件名称。多条措施不要收成一句泛利好，每条通道单独一条。
主体必须是材料里出现的名字。禁止用这些词当主体：政策主题、风险事件、公司、上市公司。
传导要写这条形式改变了哪条通道、对谁、方向。证伪写下一档哪个观测会让这句改号；写不出就填「依据不足」。
summary 不能等于标题或表面句，也不能只是原文摘录。summary 必须原样包含落地形式（landing_form）这几个字（连续出现），再写通道变化；summary 里必须出现下面之一：通道、入口、门槛、注入、承接、迁移、打通、锁定为、承载主体、收入确认、融资、资本金、股东结构、业务主体、产能、扩产。不要用「从 A 向/到/变成/转为/改成」，除非 A 能在原文或水位里原样找到。旧状态只能引用已有水位里的原句。写不出通道变化，把 new_layer 设为 false。不要编一个旧状态来过关。
evidence_excerpt 必须是正文里一段连续原文（4-240 字），必须包含 landing_form；不要用「...」「…」拼接多段。

只输出一个 JSON 对象，不要别的文字：
{{
  "surface": "表面句，入库前丢掉",
  "new_layer": false,
  "signals": [
    {{
      "subject_name": "原文里的主体",
      "subject_type": "sector|company|policy|product",
      "signal_type": "policy|order|earnings|capacity|capex|mass_production|risk",
      "polarity": "positive|negative|risk",
      "landing_form": "原文里的落地形式",
      "transmission": "这条形式改变了哪条通道",
      "falsify": "改号条件，或依据不足",
      "summary": "【summary】",
      "evidence_excerpt": "包含落地形式的原文连续片段",
      "strength": 60
    }}
  ]
}}"""


def parse_research_json(text: str) -> dict[str, Any]:
    from app.core.llm_client import _extract_json_from_code_block, _extract_json_naked, _strip_thinking_tags

    cleaned = _strip_thinking_tags(text or "")
    for extract in (_extract_json_from_code_block, _extract_json_naked):
        parsed = extract(cleaned)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("research derivation returned non-json")


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


def _strength(value: Any) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return 60
    return max(1, min(100, number))


def _confidence(strength: int, falsify: str) -> float:
    """置信度不再写死 0.8：模型强度定基准，证伪写得出来与否定打折。

    写得出具体证伪（下一档哪个观测会让这句改号）的结论更可证伪、更可信；
    只能写「依据不足」的，置信打八折。
    """
    base = 0.50 + (strength / 100.0) * 0.40  # 0.50 .. 0.90
    if "依据不足" in falsify:
        base *= 0.80
    # 能走到这里已经过了落地形式/传导/证伪门，至少「抛硬币」；上限留一点不装满。
    return round(max(0.50, min(0.95, base)), 2)


def _has_new_wording(summary: str, source: str) -> bool:
    compact_summary = _compact(summary)
    compact_source = _compact(source)
    if len(compact_summary) < 4:
        return False
    for index in range(len(compact_summary) - 3):
        if compact_summary[index : index + 4] not in compact_source:
            return True
    return False


def _is_result_form(landing_form: str) -> bool:
    return _RESULT_FORM_RE.search(landing_form) is not None


def _states_channel_shift(summary: str) -> bool:
    """二阶导要写出通道变化。推动某个结果、换种说法复述标题，都不是。"""
    if _SHIFT_RE.search(summary):
        return True
    return any(marker in summary for marker in _CHANNEL_MARKERS)


def _contiguous_excerpt(excerpt: str, landing_form: str, body: str) -> str | None:
    """Pick a contiguous span containing the landing form.

    Models sometimes join two distant spans with "..." — keep the segment that
    contains the landing form instead of rejecting an otherwise grounded signal.
    """
    if not _ELLIPSIS_RE.search(excerpt):
        return excerpt
    segments = [seg.strip() for seg in _ELLIPSIS_RE.split(excerpt) if seg.strip()]
    containing = [seg for seg in segments if _contains_span(seg, landing_form)]
    ordered = containing + [seg for seg in sorted(segments, key=len, reverse=True) if seg not in containing]
    for seg in ordered:
        if 4 <= len(seg) <= 240 and _contains_span(body, seg):
            return seg
    return None


_SUMMARY_PLACEHOLDERS = (
    "删句后的二阶导：",
    "删句后的二阶导:",
    "删句后的二阶导",
    "删句后，",
    "删句后,",
    "删句后：",
    "删句后:",
    "【summary】",
)


def _clean_summary(text: str) -> str:
    """Strip literal prompt placeholders the model sometimes copies back."""
    text = (text or "").strip()
    for prefix in _SUMMARY_PLACEHOLDERS:
        if text.startswith(prefix):
            return text[len(prefix) :].lstrip()
    return text


def _shift_prior_grounded(summary: str, source: str, prior_lines: list[str]) -> bool:
    """从 A 向 B 的 A 必须是原文或水位里的连续片段。编出来的旧状态不入库。"""
    if not _SHIFT_RE.search(summary):
        return True
    ground = "\n".join([source, *prior_lines])
    found = False
    for match in _PRIOR_SIDE_RE.finditer(summary):
        found = True
        prior = match.group(1).strip(" ，,。；;、")
        if len(_compact(prior)) < 2 or not _contains_span(ground, prior):
            return False
    return found


def _repeats_watermark(summary: str, prior_lines: list[str]) -> bool:
    compact_summary = _compact(summary)
    if not compact_summary:
        return False
    for line in prior_lines:
        compact_line = _compact(line)
        if len(compact_line) < 12:
            continue
        if compact_summary in compact_line or compact_line in compact_summary:
            return True
    return False


def _validate_signal(
    item: Any,
    *,
    payload: SourcePayload,
    text: str,
    surface: str,
    prior_lines: list[str],
) -> tuple[SignalCandidate | None, str | None]:
    if not isinstance(item, dict):
        return None, "bad_signal"
    subject = str(item.get("subject_name") or "").strip()
    subject_type = str(item.get("subject_type") or "").strip()
    signal_type = str(item.get("signal_type") or "").strip()
    polarity = str(item.get("polarity") or "").strip().lower()
    landing_form = str(item.get("landing_form") or "").strip()
    transmission = str(item.get("transmission") or "").strip()
    falsify = str(item.get("falsify") or "").strip()
    summary = _clean_summary(str(item.get("summary") or ""))
    excerpt = str(item.get("evidence_excerpt") or "").strip()
    title = (payload.title or "").strip()
    body_text = "\n".join(part for part in (payload.summary, payload.content) if part)

    if signal_type not in _SIGNAL_TYPES:
        return None, "bad_type"
    if polarity not in _POLARITIES:
        return None, "bad_polarity"
    if subject_type not in _SUBJECT_TYPES:
        return None, "bad_subject_type"
    if subject in _BANNED_SUBJECTS:
        return None, "subject_banned"
    if len(subject) < 2 or len(subject) > 40 or _compact(subject) == _compact(title):
        return None, "subject_not_in_source"
    if not _contains_span(text, subject):
        return None, "subject_not_in_source"
    if (
        len(landing_form) < 4
        or len(landing_form) > 40
        or "一系列" in landing_form
        or landing_form in _NOT_A_FORM
        or _is_result_form(landing_form)
    ):
        return None, "form_not_specific"
    if not _contains_span(body_text, landing_form):
        return None, "form_only_in_title" if _contains_span(title, landing_form) else "form_not_in_source"
    if not _contains_span(summary, landing_form):
        return None, "form_not_in_summary"
    excerpt = _contiguous_excerpt(excerpt, landing_form, body_text)
    if excerpt is None:
        return None, "excerpt_not_contiguous"
    if len(excerpt) < 4 or len(excerpt) > 240 or not _contains_span(body_text, excerpt):
        return None, "excerpt_not_in_source"
    if not _contains_span(excerpt, landing_form):
        return None, "excerpt_missing_form"
    if len(transmission) < 8 or _compact(transmission) == _compact(title):
        return None, "missing_transmission"
    if not falsify:
        return None, "missing_falsify"
    if len(summary) < 16 or len(summary) > 240:
        return None, "summary_is_surface"
    compact_summary = _compact(summary)
    if compact_summary in {_compact(title), _compact(surface), _compact(excerpt)}:
        return None, "summary_is_surface"
    if _contains_span(text, summary):
        return None, "summary_is_surface"
    if not _has_new_wording(summary, text):
        return None, "summary_not_new"
    if not _states_channel_shift(summary):
        return None, "summary_no_shift"
    if not _shift_prior_grounded(summary, text, prior_lines):
        return None, "shift_ungrounded"
    if _repeats_watermark(summary, prior_lines):
        return None, "summary_repeats_watermark"

    strength = _strength(item.get("strength"))
    metadata = dict(payload.metadata or {})
    raw_source = str(metadata.get("raw_source") or payload.source_type)
    metadata.setdefault("event_origin", resolve_event_origin(raw_source))
    metadata.setdefault("raw_source", raw_source)
    metadata.update(
        {
            "derivation": "second_order",
            "landing_form": landing_form,
            "transmission": transmission,
            "falsify": falsify,
            "surface": surface,
        }
    )
    return (
        SignalCandidate(
            source_type=llm_source_type(payload.source_type),
            source_id=payload.source_id,
            source_title=payload.title,
            source_url=payload.url,
            published_at=payload.published_at,
            subject_name=subject,
            subject_type=subject_type,
            signal_type=signal_type,
            polarity=polarity,
            strength=strength,
            confidence=_confidence(strength, falsify),
            summary=summary,
            evidence_excerpt=excerpt[:240],
            metadata=metadata,
            value_score=min(100, int(strength * 0.7 + 20)),
        ),
        None,
    )


def _rejection_parts(rejected: list[str]) -> list[str]:
    return [part for item in rejected for part in item.split(",") if part]


def _can_retry(outcome: DerivationOutcome) -> bool:
    """格式类原因再给一稿；编造形式/旧状态不重写，重写也不会变真。"""
    if outcome.candidates or outcome.stats.get("derivation_failed"):
        return False
    parts = _rejection_parts(outcome.rejected)
    return bool(parts) and all(part in _RETRY_REASONS for part in parts)


def _retry_note(rejected: list[str]) -> str:
    seen: list[str] = []
    for part in _rejection_parts(rejected):
        text = _RETRY_REASON_TEXT.get(part, part)
        if text not in seen:
            seen.append(text)
    return (
        "上一稿没有入库，原因："
        + "；".join(seen)
        + "。请只改 signals，保留原结论："
        + "landing_form 从正文原样复制 4-40 字；"
        + "summary 原样包含 landing_form，并写出通道变化；"
        + "evidence_excerpt 取包含 landing_form 的一段连续原文，不要用省略号拼接。"
        + "旧状态仍然只能来自原文或已有水位，不要新编主体、落地形式或旧状态。"
        + "改不出来就把 new_layer 设为 false，signals 设为空数组。"
    )


def _failed(reason: str) -> DerivationOutcome:
    stats = empty_derivation_stats()
    stats["derivation_failed"] = 1
    return DerivationOutcome(stats=stats, rejected=[reason])


def _accept(payload: SourcePayload, parsed: dict[str, Any], prior_lines: list[str]) -> DerivationOutcome:
    text = source_text(payload)
    surface = str(parsed.get("surface") or "").strip()
    new_layer = _as_bool(parsed.get("new_layer"))
    raw_signals = parsed.get("signals")
    if new_layer is False or (new_layer is None and not raw_signals):
        stats = empty_derivation_stats()
        stats["no_new_layer"] = 1
        return DerivationOutcome(stats=stats)
    if new_layer is not True or not isinstance(raw_signals, list):
        return _failed("bad_json")

    candidates: list[SignalCandidate] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for item in raw_signals:
        candidate, reason = _validate_signal(
            item,
            payload=payload,
            text=text,
            surface=surface,
            prior_lines=prior_lines,
        )
        if candidate is None:
            rejected.append(reason or "rejected")
            continue
        key = _compact(candidate.subject_name) + "|" + _compact(str(candidate.metadata.get("landing_form")))
        if key in seen:
            rejected.append("duplicate_form")
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) >= _MAX_SIGNALS:
            break

    stats = empty_derivation_stats()
    stats["derived"] = len(candidates)
    stats["rejected_ungrounded"] = len(rejected)
    if not candidates and not rejected:
        stats["no_new_layer"] = 1
    if rejected:
        logger.info(
            "signal derivation rejected source_id=%s reasons=%s",
            payload.source_id,
            ",".join(rejected),
        )
    if candidates:
        logger.info("signal derivation accepted source_id=%s n=%s", payload.source_id, len(candidates))
    return DerivationOutcome(candidates=candidates, stats=stats, rejected=rejected)


async def _lookup_prior_signal_lines_db(terms: list[str], *, limit: int = 8) -> list[str]:
    """按主体名精确查，板名再查摘要。查不到或超时由调用方决定不落 signal。"""
    cleaned: list[str] = []
    for term in terms:
        item = term.replace("%", "").replace("_", "").strip()
        if len(item) >= 2 and item not in cleaned:
            cleaned.append(item)
    if not cleaned:
        return []

    from sqlalchemy import select, text

    from app.core.database import async_session
    from app.signals.models import Signal

    lines: list[str] = []

    def _collect(rows: list[Any]) -> None:
        for subject, summary in rows:
            line = f"{subject}：{str(summary or '')[:180]}"
            if line not in lines:
                lines.append(line)
            if len(lines) >= limit:
                return

    async with async_session() as session:
        await session.execute(text("SET LOCAL statement_timeout = '8000ms'"))
        exact = await session.execute(
            select(Signal.subject_name, Signal.summary)
            .where(Signal.subject_name.in_(cleaned[:8]))
            .order_by(Signal.value_score.desc())
            .limit(limit)
        )
        _collect(list(exact.all()))
        boards = [term for term in cleaned if term in _BOARD_TERMS][:2]
        for term in boards:
            if len(lines) >= limit:
                break
            fuzzy = await session.execute(
                select(Signal.subject_name, Signal.summary)
                .where(Signal.summary.contains(term))
                .order_by(Signal.value_score.desc())
                .limit(4)
            )
            _collect(list(fuzzy.all()))
    return lines[:limit]


async def _lookup_prior_signal_lines_http(api_url: str, terms: list[str], *, limit: int) -> list[str]:
    api_key = os.environ.get("KNOWLEDGE_API_KEY", "")
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        resp = await client.post(
            f"{api_url}/api/v1/knowledge/signal/prior-lines",
            json={"terms": terms, "limit": limit},
            headers={"X-API-Key": api_key},
        )
        resp.raise_for_status()
        lines = resp.json().get("lines", [])
    return [str(line) for line in lines if isinstance(line, str)][:limit]


async def lookup_prior_signal_lines(terms: list[str], *, limit: int = 8) -> list[str]:
    """worker 经 Knowledge API 查询；API/scheduler 进程直接查库。"""
    if not terms:
        return []
    api_url = os.environ.get("KNOWLEDGE_API_URL", "").rstrip("/")
    if api_url:
        return await _lookup_prior_signal_lines_http(api_url, terms, limit=limit)
    return await _lookup_prior_signal_lines_db(terms, limit=limit)


async def _call_llm(prompt: str) -> str:
    from app.core.llm_client import chat_async, get_extraction_model

    model = await get_extraction_model()
    return await chat_async(
        prompt,
        model=model,
        temperature=0.0,
        timeout=60,
        max_tokens=1200,
        force_disable_thinking=True,
    )


async def derive_candidates(
    payload: SourcePayload,
    *,
    llm: ResearchLLM | None = None,
    prior_lines: list[str] | None = None,
) -> DerivationOutcome:
    text = source_text(payload)
    if not text.strip():
        stats = empty_derivation_stats()
        stats["no_new_layer"] = 1
        return DerivationOutcome(stats=stats)
    if is_price_tape(text):
        stats = empty_derivation_stats()
        stats["skipped_tape"] = 1
        logger.info("signal derivation skipped tape source_id=%s", payload.source_id)
        return DerivationOutcome(stats=stats)

    if prior_lines is None:
        try:
            prior_lines = await lookup_prior_signal_lines(watermark_terms(text))
        except Exception as exc:  # noqa: BLE001 — 水位没查到就不能声称「新」
            logger.warning(
                "signal derivation watermark failed source_id=%s (%s)",
                payload.source_id,
                exc.__class__.__name__,
            )
            return _failed("watermark_unavailable")

    prompt = build_research_prompt(payload, prior_lines)
    caller = llm or _call_llm
    try:
        raw = await caller(prompt)
        parsed = parse_research_json(raw)
    except Exception as exc:  # noqa: BLE001 — 模型失败写零条，不退回规则
        logger.warning(
            "signal derivation failed source_id=%s (%s)",
            payload.source_id,
            exc.__class__.__name__,
        )
        return _failed("llm_failed")
    outcome = _accept(payload, parsed, prior_lines)
    if not _can_retry(outcome):
        return outcome
    logger.info(
        "signal derivation retry source_id=%s reasons=%s",
        payload.source_id,
        ",".join(outcome.rejected),
    )
    try:
        retry_prompt = (
            prompt
            + "\n\n上一稿（未入库）：\n"
            + raw[:2000]
            + "\n\n"
            + _retry_note(outcome.rejected)
        )
        raw = await caller(retry_prompt)
        parsed = parse_research_json(raw)
    except Exception as exc:  # noqa: BLE001 — 改稿失败就保持第一稿的零条，不把整单打成失败重试
        logger.warning(
            "signal derivation retry failed source_id=%s (%s)",
            payload.source_id,
            exc.__class__.__name__,
        )
        return outcome
    return _accept(payload, parsed, prior_lines)


def records_from_candidates(candidates: list[SignalCandidate]) -> list[dict[str, Any]]:
    from app.signals.event_ingestion import _signal_values

    return [_signal_values(candidate) for candidate in candidates]
