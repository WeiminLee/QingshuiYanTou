"""Rule-based IRM answer classifier for graded extraction strategy.

Categories (in priority order):
  empty    — Boilerplate-only, no substantive content
  complex  — Long-form management explanation (≥300 chars)
  defer    — Defers to public filing, little independent info
  data     — Contains quantitative data (revenue, percentages, metrics)
  simple   — Everything else with some content
"""

from __future__ import annotations

import re

BOILERPLATE_PREFIXES = [
    "尊敬的投资者，您好！",
    "尊敬的投资者，您好。",
    "尊敬的投资者您好！",
    "尊敬的投资者您好。",
    "投资者您好，",
    "投资者您好！",
    "投资者您好。",
    "您好，",
    "您好！",
    "尊敬的投资者：",
]

BOILERPLATE_SUFFIXES = [
    "感谢您对公司的关注。",
    "感谢您对公司的关注！",
    "感谢您的关注。",
    "感谢您的关注！",
    "感谢关注。",
    "感谢关注！",
    "谢谢您的关注。",
    "谢谢您的关注！",
    "谢谢关注。",
    "谢谢关注！",
    "以上，感谢您对公司的关注。",
    "再次感谢您对公司的关注。",
]

DEFERRAL_PATTERNS = [
    "以公告为准",
    "以公司公告为准",
    "详见公告",
    "参见公告",
    "查阅公告",
    "请以公告",
    "详见公司",
    "详见公司于",
    "将于公告中披露",
    "请关注公司公告",
    "请查阅公司在",
    "请投资者关注公司公告",
    "将在定期报告中",
    "会在定期报告",
    "信息披露义务",
    "及时信披",
    "及时披露",
    "将会按照相关规定",
]


def _strip_irm_boilerplate(text: str) -> str:
    """Strip common IRM boilerplate prefix/suffix to extract core content."""
    stripped = text
    for suffix in BOILERPLATE_SUFFIXES:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    for prefix in BOILERPLATE_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break
    return stripped.strip()


def _has_deferral(text: str) -> bool:
    for pattern in DEFERRAL_PATTERNS:
        if pattern in text:
            return True
    return False


def _has_quantitative_data(text: str) -> bool:
    if re.search(r"\d+\.?\d*\s*(亿|万|千)?\s*元", text):
        return True
    if re.search(r"\d+\.?\d*\s*%", text):
        return True
    if re.search(r"\d{4,}\s*(吨|户|GWh|MWh|万股|千瓦|平方米|公里|人)", text):
        return True
    fin_patterns = [
        r"(?:营收|净利润|毛利率|收入|利润|现金流|负债|资产|权益)\s*[为:：]?\s*\d+",
        r"(?:增长|下降|提升|降低|减少|增加)\s*\d+\.?\d*\s*[%百分点]",
        r"(?:同比增长|环比增长|同比下滑|环比下滑)\s*\d+\.?\d*\s*%",
    ]
    for pat in fin_patterns:
        if re.search(pat, text):
            return True
    return False


def classify_irm_answer(answer: str) -> str:
    """Classify an IRM answer into a quality category.

    Args:
        answer: Raw IRM answer text (from metadata.answer).

    Returns:
        One of: "empty", "complex", "defer", "data", "simple"
    """
    if not answer or not answer.strip():
        return "empty"

    core = _strip_irm_boilerplate(answer)
    core_len = len(core)

    # 1. empty: after stripping boilerplate, essentially nothing
    if core_len < 3:
        return "empty"

    # 2. complex: long-form substantive answer
    if len(answer) >= 300:
        return "complex"

    # 3. defer: primarily refers to public filing
    if _has_deferral(answer) and core_len < 50:
        return "defer"

    # 4. data: contains quantitative information
    if _has_quantitative_data(core):
        return "data"

    # 5. simple: everything else with some content
    return "simple"


def classify_irm_evidence(evidence: dict) -> str:
    """Classify an IRM evidence document.

    Reads both metadata.answer and text_excerpt to extract the answer.
    """
    metadata = evidence.get("metadata") or {}
    answer = metadata.get("answer") or ""
    if not answer:
        text = evidence.get("text_excerpt") or ""
        if "答：" in text:
            answer = text.split("答：", 1)[1].strip()
        else:
            answer = text
    return classify_irm_answer(answer)


_TIER_ORDER = {"empty": 0, "defer": 1, "simple": 2, "data": 3, "complex": 4}


def extraction_tier(category: str) -> int:
    """Return the extraction depth tier for a category.

    0: vector only (no KG)
    1: vector + rules only
    2: vector + rules + LLM
    """
    if category in ("empty", "defer"):
        return 0
    if category in ("simple", "data"):
        return 1
    if category == "complex":
        return 2
    return 0


def needs_llm(category: str) -> bool:
    return category == "complex"


def needs_rules(category: str) -> bool:
    return category in ("simple", "data", "complex")
