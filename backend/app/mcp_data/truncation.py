"""Evidence text truncation aligned with LangChain fetch_evidence (8k chars)."""
from __future__ import annotations

_MAX_EVIDENCE_TEXT = 8000


def truncate_evidence_text(text: str, limit: int = _MAX_EVIDENCE_TEXT) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return (
        text[:limit]
        + f"\n...[原文过长已截断：共 {len(text)} 字符，仅显示前 "
        f"{limit} 字符；如需更多请用 backlinks 缩小范围或换成更精确的证据 ID]"
    )
