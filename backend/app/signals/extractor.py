from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SourcePayload:
    source_type: str
    source_id: str
    title: str
    content: str
    summary: str
    published_at: datetime | None
    url: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalCandidate:
    source_type: str
    source_id: str
    source_title: str
    source_url: str | None
    published_at: datetime | None
    subject_name: str
    subject_type: str
    signal_type: str
    polarity: str
    strength: int
    confidence: float
    summary: str
    evidence_excerpt: str
    metadata: dict[str, Any] = field(default_factory=dict)
    value_score: int = 0


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def stable_signal_id(candidate: SignalCandidate) -> str:
    raw = "|".join(
        [
            candidate.source_type,
            candidate.source_id,
            _normalize_text(candidate.subject_name),
            candidate.signal_type,
            _normalize_text(candidate.evidence_excerpt[:120]),
        ]
    )
    return f"SIG:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


class RuleSignalExtractor:
    """Deterministic rule extractor for first-pass signal discovery."""

    _PATTERNS: dict[str, dict[str, Any]] = {
        "mass_production": {
            "keywords": ("规模量产", "大规模量产", "批量交付", "量产", "达产"),
            "subject_type": "product",
            "polarity": "positive",
            "base_strength": 84,
        },
        "capacity": {
            "keywords": ("扩产", "新增产能", "投产", "产能爬坡", "项目开工"),
            "subject_type": "sector",
            "polarity": "positive",
            "base_strength": 78,
        },
        "policy": {
            "keywords": ("十五五", "政策", "规划", "补贴", "国产替代", "监管"),
            "subject_type": "policy",
            "polarity": "positive",
            "base_strength": 76,
        },
        "capex": {
            "keywords": ("资本开支", "capex", "算力投入", "设备采购"),
            "subject_type": "sector",
            "polarity": "positive",
            "base_strength": 80,
        },
        "earnings": {
            "keywords": ("业绩预增", "超预期", "扭亏", "毛利率", "净利润"),
            "subject_type": "company",
            "polarity": "positive",
            "base_strength": 82,
        },
        "order": {
            "keywords": ("大额订单", "长期合同", "客户导入", "战略合作", "订单"),
            "subject_type": "company",
            "polarity": "positive",
            "base_strength": 82,
        },
        "risk": {
            "keywords": ("风险", "诉讼", "处罚", "减值", "停产", "订单延期"),
            "subject_type": "company",
            "polarity": "risk",
            "base_strength": 76,
        },
    }

    _STRONG_MARKERS = ("显著", "大规模", "首次", "超预期", "重大", "大幅")

    def extract(self, payload: SourcePayload) -> list[SignalCandidate]:
        text = "\n".join(v for v in [payload.title, payload.summary, payload.content] if v)
        if not text.strip():
            return []

        candidates: list[SignalCandidate] = []
        seen_types: set[str] = set()
        for signal_type, cfg in self._PATTERNS.items():
            match = self._find_keyword(text, cfg["keywords"])
            if not match or signal_type in seen_types:
                continue
            sentence = self._sentence_for_keyword(text, match)
            subject_name = self._infer_subject(payload, sentence, signal_type)
            strength = self._score_strength(sentence, cfg["base_strength"])
            confidence = 0.78 if payload.source_type in {"announcement", "evidence"} else 0.68
            value_score = min(100, int(strength * 0.65 + confidence * 25))
            candidates.append(
                SignalCandidate(
                    source_type=payload.source_type,
                    source_id=payload.source_id,
                    source_title=payload.title,
                    source_url=payload.url,
                    published_at=payload.published_at,
                    subject_name=subject_name,
                    subject_type=cfg["subject_type"],
                    signal_type=signal_type,
                    polarity=cfg["polarity"],
                    strength=strength,
                    confidence=confidence,
                    summary=sentence[:160],
                    evidence_excerpt=sentence[:240],
                    metadata=dict(payload.metadata or {}),
                    value_score=value_score,
                )
            )
            seen_types.add(signal_type)
        return candidates

    def _find_keyword(self, text: str, keywords: tuple[str, ...]) -> str | None:
        lower_text = text.lower()
        for keyword in keywords:
            if keyword in text or keyword.lower() in lower_text:
                return keyword
        return None

    def _sentence_for_keyword(self, text: str, keyword: str) -> str:
        sentences = [s.strip() for s in re.split(r"[。！？；;\n]", text) if s.strip()]
        for sentence in sentences:
            if keyword in sentence or keyword.lower() in sentence.lower():
                return sentence
        return sentences[0] if sentences else text.strip()

    def _infer_subject(self, payload: SourcePayload, sentence: str, signal_type: str) -> str:
        tags = payload.metadata.get("tags") if isinstance(payload.metadata, dict) else None
        if isinstance(tags, list) and tags:
            return str(tags[0])
        if signal_type == "policy":
            return "算力基础设施" if "算力" in sentence else "政策主题"
        if signal_type == "capex":
            return "资本开支"
        if signal_type == "risk":
            return "风险事件"
        return (payload.title or sentence)[:24]

    def _score_strength(self, sentence: str, base_strength: int) -> int:
        boost = sum(4 for marker in self._STRONG_MARKERS if marker in sentence)
        return max(0, min(100, base_strength + boost))

