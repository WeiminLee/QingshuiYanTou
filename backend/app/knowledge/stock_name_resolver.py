"""
StockNameResolver — 股票名称解析的唯一真相源

PostgreSQL stocks + company_profiles 表作为主数据源，
supplemental_aliases.json 作为补充（海外公司 + 手动别名）。

启动时 warm_cache() 从 PostgreSQL 加载全量映射到内存，
之后所有查询都是同步的内存 dict 读取，零 IO。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

_SUPPLEMENTAL_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "supplemental_aliases.json"


class StockNameResolver:
    """
    股票名称 → ts_code 解析器。

    数据来源：
      1. PostgreSQL stocks 表（简称 + industry）
      2. PostgreSQL company_profiles 表（全称 com_name）
      3. supplemental_aliases.json（海外公司 + 手动别名 + sector_tags）

    所有查找方法都是同步的（读内存 dict），warm_cache() 是异步的（查 PostgreSQL）。
    """

    def __init__(self) -> None:
        # A-share: name variant → ts_code
        self._name_to_ts_code: dict[str, str] = {}
        # A-share: ts_code → all known name variants
        self._ts_code_to_names: dict[str, list[str]] = {}
        # A-share: ts_code → industry
        self._ts_code_to_industry: dict[str, str] = {}
        # Non-A-share: name variant → entity_id (CO_XXX or CO:{hash})
        self._co_name_to_id: dict[str, str] = {}
        # Non-A-share: entity_id → all known name variants
        self._co_id_to_names: dict[str, list[str]] = {}
        # Non-A-share: entity_id → sector_tags
        self._co_id_to_sectors: dict[str, set[str]] = {}
        # Non-A-share: entity_id → ts_code (if available)
        self._co_id_to_ts_code: dict[str, str] = {}
        # B12 fix: 缓存 supplemental JSON 内容
        self._supplemental_cache: dict = {}
        self._loaded: bool = False

    async def warm_cache(self) -> None:
        """
        从 PostgreSQL + supplemental_aliases.json 加载全量映射。
        在 app lifespan 中调用一次。
        """
        if self._loaded:
            return

        # Step 1: Load from PostgreSQL
        pg_count = await self._load_from_postgresql()

        # Step 2: Merge supplemental aliases (adds aliases + overseas)
        supp_count = self._load_supplemental()

        self._loaded = True
        total = len(self._name_to_ts_code) + len(self._co_name_to_id)
        logger.info(
            "StockNameResolver 已加载: %d 条 A-share 映射 (PG=%d, 补充=%d), "
            "%d 条非 A-share 映射, 总计 %d 条名称",
            len(self._name_to_ts_code), pg_count, supp_count,
            len(self._co_name_to_id), total,
        )

    async def _load_from_postgresql(self) -> int:
        """从 PostgreSQL stocks + company_profiles 加载 A-share 映射。"""
        try:
            from app.core.database import async_session
            from app.models.models import Stock, CompanyProfile

            async with async_session() as db:
                # Load stocks (简称 + industry)
                stock_result = await db.execute(
                    select(Stock.ts_code, Stock.name, Stock.industry)
                )
                stocks = stock_result.fetchall()

                # Load company_profiles (全称)
                profile_result = await db.execute(
                    select(CompanyProfile.ts_code, CompanyProfile.com_name)
                )
                profiles = profile_result.fetchall()

            # Build name → ts_code mappings
            added = 0
            for ts_code, name, industry in stocks:
                if not name or not ts_code:
                    continue
                name_lower = name.lower()
                if name_lower not in self._name_to_ts_code:
                    self._name_to_ts_code[name_lower] = ts_code
                    added += 1
                # ts_code itself as a lookup key
                self._name_to_ts_code[ts_code.lower()] = ts_code
                # Track all variants per ts_code
                names_list = self._ts_code_to_names.setdefault(ts_code, [])
                if name not in names_list:
                    names_list.append(name)
                # Industry
                if industry:
                    self._ts_code_to_industry[ts_code] = industry

            # Merge company_profiles (全称 as additional variant)
            for ts_code, com_name in profiles:
                if not com_name or not ts_code:
                    continue
                com_name_lower = com_name.lower()
                if com_name_lower not in self._name_to_ts_code:
                    self._name_to_ts_code[com_name_lower] = ts_code
                names_list = self._ts_code_to_names.setdefault(ts_code, [])
                if com_name not in names_list:
                    names_list.append(com_name)

            logger.info("PostgreSQL 加载: %d stocks, %d profiles, %d 新映射",
                        len(stocks), len(profiles), added)
            return added

        except Exception as e:
            logger.warning("PostgreSQL 加载失败，仅使用补充数据: %s", e)
            return 0

    def _load_supplemental(self) -> int:
        """从 supplemental_aliases.json 加载海外公司 + 手动别名。"""
        if not _SUPPLEMENTAL_PATH.exists():
            logger.info("supplemental_aliases.json 不存在，跳过")
            return 0

        try:
            with open(_SUPPLEMENTAL_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("supplemental_aliases.json 加载失败: %s", e)
            return 0

        # B12 fix: 缓存 JSON 内容，供 get_sector_tags 使用
        self._supplemental_cache = data

        added = 0
        for canonical_key, entry in data.items():
            names = entry.get("names", [])
            ts_code = entry.get("ts_code", "")
            sector_tags = entry.get("sector_tags", [])
            is_overseas = canonical_key.startswith("CO_")

            if is_overseas or not ts_code:
                # Non-A-share: use CO_XXX or generate CO:{hash} entity_id
                entity_id = canonical_key if is_overseas else self._generate_co_id(canonical_key)
                for name in names:
                    self._co_name_to_id[name.lower()] = entity_id
                self._co_id_to_names[entity_id] = names
                self._co_id_to_sectors[entity_id] = set(sector_tags)
                if ts_code:
                    self._co_id_to_ts_code[entity_id] = ts_code
                added += 1
            else:
                # A-share with manual aliases: merge into existing ts_code mapping
                for name in names:
                    name_lower = name.lower()
                    if name_lower not in self._name_to_ts_code:
                        self._name_to_ts_code[name_lower] = ts_code
                        added += 1
                    names_list = self._ts_code_to_names.setdefault(ts_code, [])
                    if name not in names_list:
                        names_list.append(name)
                # Merge sector_tags into industry
                if sector_tags:
                    existing = self._ts_code_to_industry.get(ts_code, "")
                    if existing:
                        # Combine industry + sector_tags
                        self._ts_code_to_industry[ts_code] = existing
                    # Store sector_tags as extra info (accessible via get_sector_tags)
                    # We add sector_tags as additional name variants for search
                    for tag in sector_tags:
                        tag_lower = tag.lower()
                        if tag_lower not in self._name_to_ts_code:
                            # Don't map sector tags to ts_code — they're not company names
                            pass

        logger.info("supplemental_aliases.json 加载: %d 条补充映射", added)
        return added

    @staticmethod
    def _generate_co_id(name: str) -> str:
        """为非上市国内公司生成 entity_id: CO:{md5[:12]}"""
        h = hashlib.md5(name.encode("utf-8")).hexdigest()[:12].upper()
        return f"CO:{h}"

    # ── Public lookup methods (all synchronous, in-memory) ─────────────

    def resolve(self, name: str) -> Optional[str]:
        """
        解析公司名称 → ts_code。
        返回 None 表示未找到。
        """
        if not name:
            return None
        name_lower = name.lower()
        # A-share lookup
        ts_code = self._name_to_ts_code.get(name_lower)
        if ts_code:
            return ts_code
        # Non-A-share: check if it maps to a CO_ entity with ts_code
        co_id = self._co_name_to_id.get(name_lower)
        if co_id:
            return self._co_id_to_ts_code.get(co_id)
        return None

    def resolve_entity_id(self, name: str) -> tuple[str, str]:
        """
        解析公司名称 → (entity_id, canonical_name)。
        替代 kg_extractor._resolve_company_id()。

        Returns:
          - ("C:{ts_code}", stocks.name) for A-share
          - ("CO_XXX", canonical_key) for overseas
          - ("CO:{hash}", name) as fallback for unknown
        """
        if not name:
            return ("CO:UNKNOWN", name)

        name_lower = name.lower()

        # A-share: name → ts_code → entity_id
        ts_code = self._name_to_ts_code.get(name_lower)
        if ts_code:
            entity_id = f"C:{ts_code}"
            # Return the primary name (from stocks table, first in names list)
            names_list = self._ts_code_to_names.get(ts_code, [])
            canonical = names_list[0] if names_list else name
            return (entity_id, canonical)

        # Non-A-share: name → CO_ entity_id
        co_id = self._co_name_to_id.get(name_lower)
        if co_id:
            names_list = self._co_id_to_names.get(co_id, [])
            canonical = names_list[0] if names_list else name
            return (co_id, canonical)

        # Unknown: generate hash-based entity_id
        return (self._generate_co_id(name), name)

    def get_aliases(self, ts_code: str) -> list[str]:
        """获取 ts_code 的所有已知名称变体。"""
        return self._ts_code_to_names.get(ts_code, [])

    def get_sector_tags(self, name: str) -> set[str]:
        """
        获取公司名称的 sector/industry 标签。
        合并 PostgreSQL industry + supplemental sector_tags。
        """
        tags: set[str] = set()
        if not name:
            return tags

        name_lower = name.lower()

        # A-share: check via ts_code
        ts_code = self._name_to_ts_code.get(name_lower)
        if ts_code:
            industry = self._ts_code_to_industry.get(ts_code, "")
            if industry:
                tags.add(industry)
            # B12 fix: 使用缓存的 supplemental 数据，避免每次调用都读文件
            # _supplemental_cache 已在 warm_cache 中加载
            if self._supplemental_cache:
                for entry in self._supplemental_cache.values():
                    if entry.get("ts_code") == ts_code:
                        for tag in entry.get("sector_tags", []):
                            tags.add(tag)
                        break

        # Non-A-share: check via CO_ entity_id
        co_id = self._co_name_to_id.get(name_lower)
        if co_id:
            tags.update(self._co_id_to_sectors.get(co_id, set()))

        return tags

    def is_same_company(self, a: str, b: str) -> bool:
        """
        判断两个名称是否属于同一公司。
        替代 entity_resolver._cross_language_alias()。
        """
        if not a or not b:
            return False
        a_lower = a.lower()
        b_lower = b.lower()

        # Both resolve to same ts_code?
        a_ts = self._name_to_ts_code.get(a_lower)
        b_ts = self._name_to_ts_code.get(b_lower)
        if a_ts and b_ts and a_ts == b_ts:
            return True

        # Both resolve to same CO_ entity_id?
        a_co = self._co_name_to_id.get(a_lower)
        b_co = self._co_name_to_id.get(b_lower)
        if a_co and b_co and a_co == b_co:
            return True

        # Cross: one is A-share, one is non-A-share but same company?
        if a_ts:
            # Check if b maps to a CO_ entity with same ts_code
            b_co = self._co_name_to_id.get(b_lower)
            if b_co and self._co_id_to_ts_code.get(b_co) == a_ts:
                return True
        if b_ts:
            a_co = self._co_name_to_id.get(a_lower)
            if a_co and self._co_id_to_ts_code.get(a_co) == b_ts:
                return True

        return False

    def size(self) -> int:
        """已加载的名称映射总数。"""
        return len(self._name_to_ts_code) + len(self._co_name_to_id)


# ── Singleton ──────────────────────────────────────────────────────────

_resolver: StockNameResolver | None = None


def get_stock_name_resolver() -> StockNameResolver:
    """获取全局 StockNameResolver 单例。"""
    global _resolver
    if _resolver is None:
        _resolver = StockNameResolver()
    return _resolver