"""记忆系统纯工具函数：无外部依赖，便于单测。"""

from __future__ import annotations

import re
import unicodedata


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)}


def jaccard_similarity(a: str, b: str) -> float:
    """字符 2-gram 集合的 Jaccard 相似度，0.0–1.0。

    任一串长度 < 2 时无法生成 2-gram，退化为「完全相等则 1.0，否则 0.0」。
    """
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa and not sb:
        return 1.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def normalize_subject(s: str) -> str:
    """subject 归一化：NFKC 全角转半角 + 合并内部空白 + strip。"""
    if not s:
        return ""
    normalized = unicodedata.normalize("NFKC", s)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()
