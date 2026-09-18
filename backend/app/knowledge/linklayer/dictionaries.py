# backend/app/knowledge/linklayer/dictionaries.py
"""种子词表加载：维度/阶梯/指标词表（spec §4.2 三层词表的封闭类部分）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass
class Dimension:
    name: str
    kind: str  # staged | numeric
    stages: list[dict] = field(default_factory=list)  # [{level, words}]


@dataclass
class Vocabulary:
    dimensions: dict[str, Dimension] = field(default_factory=dict)
    metric_words: set[str] = field(default_factory=set)


@lru_cache(maxsize=1)
def load_vocabulary() -> Vocabulary:
    path = Path(__file__).parent / "data" / "dimensions.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    vocab = Vocabulary()
    for dim in raw.get("dimensions", []):
        vocab.dimensions[dim["name"]] = Dimension(
            name=dim["name"], kind=dim["kind"], stages=dim.get("stages", [])
        )
    vocab.metric_words = set(raw.get("metrics", []))
    return vocab
