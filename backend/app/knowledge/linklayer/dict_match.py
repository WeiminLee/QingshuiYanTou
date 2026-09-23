# backend/app/knowledge/linklayer/dict_match.py
"""封闭类词表的确定性匹配：subject（别名表）+ dimension（指标词）+ stage（阶梯词）。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.knowledge.linklayer.dictionaries import Vocabulary

logger = logging.getLogger(__name__)

# backend/data/company_aliases.json（backend 根目录下的数据文件）
COMPANY_ALIASES_PATH = Path(__file__).resolve().parents[3] / "data" / "company_aliases.json"


@dataclass
class DictMatch:
    norm_text: str
    layer: str  # subject | dimension | stage
    dimension: str | None = None
    level: int | None = None
    span_start: int = 0
    span_end: int = 0


class SubjectIndex:
    """公司别名 → 规范名（上市优先 ts_code）。v1 从 company_aliases.json + stocks 表构建。"""

    def __init__(self, alias_to_norm: dict[str, str]) -> None:
        self.alias_to_norm = dict(alias_to_norm)

    def match(self, text: str):
        for alias, norm in self.alias_to_norm.items():
            start = 0
            while (start := text.find(alias, start)) >= 0:
                yield DictMatch(
                    norm_text=norm, layer="subject",
                    span_start=start, span_end=start + len(alias),
                )
                start += len(alias)


def load_alias_table() -> dict[str, str]:
    """读取 backend/data/company_aliases.json，返回 alias → 规范名。

    文档结构：{规范全称: {"names": [别名...], "listing": bool, "ts_code": "..."}}。
    已上市主体（有 ts_code）规范名为 ts_code，否则为规范全称（即 JSON key）。
    文件缺失/损坏时警告并返回空表，不阻断调用方。
    """
    if not COMPANY_ALIASES_PATH.is_file():
        logger.warning("公司别名表不存在，subject 层索引为空：%s", COMPANY_ALIASES_PATH)
        return {}
    try:
        raw = json.loads(COMPANY_ALIASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("公司别名表读取失败：%s", COMPANY_ALIASES_PATH)
        return {}
    if not isinstance(raw, dict):
        logger.warning("公司别名表结构异常（顶层非 dict），subject 层索引为空")
        return {}

    alias_to_norm: dict[str, str] = {}
    for full_name, info in raw.items():
        if not isinstance(info, dict):
            continue
        names = info.get("names") or []
        ts_code = str(info.get("ts_code") or "").strip()
        norm = ts_code or full_name
        alias_to_norm.setdefault(full_name, norm)
        for name in names:
            if isinstance(name, str) and name:
                alias_to_norm.setdefault(name, norm)
    return alias_to_norm


async def build_subject_index(use_db: bool = True) -> SubjectIndex:
    """构建 subject 层别名索引（JSON 别名 + PG stocks 表名，均尽力而为）。

    use_db=False 时跳过 PG（远端 worker 无数据库通道）。
    """
    alias_to_norm = load_alias_table()
    if not use_db:
        return SubjectIndex(alias_to_norm=alias_to_norm)
    try:
        from sqlalchemy import select

        from app.core.database import async_session
        from app.models.models import Stock

        async with async_session() as session:
            rows = await session.execute(select(Stock.ts_code, Stock.name))
            for ts_code, name in rows:
                if name:
                    alias_to_norm.setdefault(name, ts_code)
    except Exception:  # noqa: BLE001 — PG 不可达时降级为纯 JSON 索引
        logger.warning("stocks 表查询失败，跳过股票名索引（仅保留 JSON 别名）", exc_info=True)
    return SubjectIndex(alias_to_norm=alias_to_norm)


def match_all(text: str, vocab: Vocabulary, subject_index: SubjectIndex) -> list[DictMatch]:
    results: list[DictMatch] = list(subject_index.match(text))
    for name, dim in vocab.dimensions.items():
        for stage in dim.stages:
            for word in stage["words"]:
                start = 0
                while (start := text.find(word, start)) >= 0:
                    results.append(
                        DictMatch(
                            norm_text=word, layer="stage", dimension=name,
                            level=stage["level"], span_start=start,
                            span_end=start + len(word),
                        )
                    )
                    start += len(word)
        if name in text:  # 维度名本身（如"毛利率"）也作为 dimension 关键字
            start = text.find(name)
            results.append(
                DictMatch(norm_text=name, layer="dimension", dimension=name,
                          span_start=start, span_end=start + len(name))
            )
    for word in vocab.metric_words:
        start = text.find(word)
        if start >= 0:
            results.append(
                DictMatch(norm_text=word, layer="dimension", dimension=word,
                          span_start=start, span_end=start + len(word))
            )
    return results
