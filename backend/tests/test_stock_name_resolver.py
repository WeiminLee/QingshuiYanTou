"""Tests for StockNameResolver — A-share name → ts_code resolution."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.stock_name_resolver import StockNameResolver


@pytest.fixture
def resolver_with_mocked_pg():
    """Build a resolver with PostgreSQL mocked to return fixed sample data."""
    resolver = StockNameResolver()

    # Mock stocks: (ts_code, name, industry)
    stock_rows = [
        ("688981.SH", "中芯国际", "半导体"),
        ("300750.SZ", "宁德时代", "电池"),
        ("600519.SH", "贵州茅台", "白酒"),
    ]
    # Mock profiles: (ts_code, com_name)
    profile_rows = [
        ("688981.SH", "中芯国际半导体制造有限公司"),
        ("300750.SZ", "宁德时代新能源科技股份有限公司"),
    ]

    async def fake_load_postgresql(self):
        for ts_code, name, industry in stock_rows:
            self._name_to_ts_code[name.lower()] = ts_code
            self._name_to_ts_code[ts_code.lower()] = ts_code
            self._ts_code_to_names.setdefault(ts_code, []).append(name)
            if industry:
                self._ts_code_to_industry[ts_code] = industry
        for ts_code, com_name in profile_rows:
            self._name_to_ts_code[com_name.lower()] = ts_code
            self._ts_code_to_names.setdefault(ts_code, []).append(com_name)
        return len(stock_rows)

    with patch.object(StockNameResolver, "_load_from_postgresql", fake_load_postgresql), \
         patch.object(StockNameResolver, "_load_supplemental", lambda self: 0):
        import asyncio
        asyncio.run(resolver.warm_cache())
    return resolver


def test_resolve_short_name(resolver_with_mocked_pg):
    """简称 → ts_code"""
    assert resolver_with_mocked_pg.resolve("中芯国际") == "688981.SH"
    assert resolver_with_mocked_pg.resolve("宁德时代") == "300750.SZ"


def test_resolve_full_name(resolver_with_mocked_pg):
    """全称 → ts_code"""
    assert resolver_with_mocked_pg.resolve("中芯国际半导体制造有限公司") == "688981.SH"


def test_resolve_ts_code_itself(resolver_with_mocked_pg):
    """ts_code 输入直接返回"""
    assert resolver_with_mocked_pg.resolve("688981.SH") == "688981.SH"
    assert resolver_with_mocked_pg.resolve("688981.sh") == "688981.SH"  # 大小写不敏感


def test_resolve_unknown_returns_none(resolver_with_mocked_pg):
    """未知名称 → None"""
    assert resolver_with_mocked_pg.resolve("不存在的公司") is None


def test_resolve_empty_string(resolver_with_mocked_pg):
    """空字符串 → None"""
    assert resolver_with_mocked_pg.resolve("") is None


def test_resolve_entity_id_a_share(resolver_with_mocked_pg):
    """A-share 公司 → C:{ts_code}"""
    entity_id, canonical = resolver_with_mocked_pg.resolve_entity_id("中芯国际")
    assert entity_id == "C:688981.SH"
    assert canonical == "中芯国际"


def test_resolve_entity_id_unknown_uses_hash(resolver_with_mocked_pg):
    """未知公司 → CO:{hash} fallback"""
    entity_id, canonical = resolver_with_mocked_pg.resolve_entity_id("某未知公司")
    assert entity_id.startswith("CO:")
    assert len(entity_id) == 15  # "CO:" + 12 hex chars
    assert canonical == "某未知公司"


def test_get_aliases(resolver_with_mocked_pg):
    """ts_code → 所有名称变体"""
    aliases = resolver_with_mocked_pg.get_aliases("688981.SH")
    assert "中芯国际" in aliases
    assert "中芯国际半导体制造有限公司" in aliases


def test_get_sector_tags_from_industry(resolver_with_mocked_pg):
    """A-share 公司 sector_tags 来自 stocks.industry"""
    tags = resolver_with_mocked_pg.get_sector_tags("中芯国际")
    assert "半导体" in tags


def test_is_same_company_same_ts_code(resolver_with_mocked_pg):
    """简称与全称属于同一公司"""
    assert resolver_with_mocked_pg.is_same_company(
        "中芯国际", "中芯国际半导体制造有限公司"
    ) is True


def test_is_same_company_different(resolver_with_mocked_pg):
    """不同公司"""
    assert resolver_with_mocked_pg.is_same_company("中芯国际", "贵州茅台") is False


def test_is_same_company_unknown(resolver_with_mocked_pg):
    """未知名称"""
    assert resolver_with_mocked_pg.is_same_company("中芯国际", "某未知") is False
    assert resolver_with_mocked_pg.is_same_company("", "中芯国际") is False


def test_size(resolver_with_mocked_pg):
    """size() 返回名称映射总数"""
    assert resolver_with_mocked_pg.size() > 0


def test_warm_cache_idempotent(resolver_with_mocked_pg):
    """重复调用 warm_cache 不重新加载"""
    initial_size = resolver_with_mocked_pg.size()
    import asyncio
    asyncio.run(resolver_with_mocked_pg.warm_cache())
    assert resolver_with_mocked_pg.size() == initial_size


def test_fallback_when_postgres_unavailable():
    """PostgreSQL 不可用时优雅降级（_load_from_postgresql 内部 try/except 返回 0）"""
    resolver = StockNameResolver()

    async def no_op_load(self):
        # _load_from_postgresql 内部 try/except 会捕获异常并返回 0
        return 0

    with patch.object(StockNameResolver, "_load_from_postgresql", no_op_load), \
         patch.object(StockNameResolver, "_load_supplemental", lambda self: 0):
        import asyncio
        asyncio.run(resolver.warm_cache())
        # 系统功能降级但不崩溃
        assert resolver.resolve("任意公司") is None
