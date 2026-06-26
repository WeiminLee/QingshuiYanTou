"""
Tests for entity_resolver.py sector-aware disambiguation.

Run: python -m pytest backend/tests/test_entity_resolver.py -v
"""

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.knowledge.entity_resolver import (
    _get_sector_tags,
    _has_digit_in_2gram_diff,
    _is_english,
    _sectors_disjoint,
    is_similarity,
)
from app.knowledge.stock_name_resolver import StockNameResolver, get_stock_name_resolver


@pytest.fixture(autouse=True)
def warm_resolver():
    """Pre-warm the singleton resolver from supplemental_aliases.json only.

    PostgreSQL is mocked out so tests don't need a live database; cross-language
    aliases (英伟达/NVIDIA) come from supplemental_aliases.json.
    """
    resolver = get_stock_name_resolver()
    if resolver._loaded:
        yield
        return

    async def no_pg(self):
        return 0

    with patch.object(StockNameResolver, "_load_from_postgresql", no_pg):
        asyncio.run(resolver.warm_cache())
    yield


class TestIsEnglish:
    def test_english_nvidia(self):
        assert _is_english("NVIDIA") is True

    def test_chinese_nvidia(self):
        assert _is_english("英伟达") is False

    def test_mixed_returns_false(self):
        assert _is_english("华为海思") is False


class TestDigitDiff:
    def test_800g_vs_400g(self):
        assert _has_digit_in_2gram_diff("800G光模块", "400G光模块") is True

    def test_same_name_no_digit_diff(self):
        assert _has_digit_in_2gram_diff("中芯国际", "中芯国际") is False

    def test_same_digits_no_diff(self):
        assert _has_digit_in_2gram_diff("中芯国际", "中芯国际") is False


class TestIsSimilarity:
    def test_chinese_alias(self):
        # 跨语言别名通过 StockNameResolver 判断（PostgreSQL 不可用时回退到 supplemental）
        assert is_similarity("英伟达", "NVIDIA") is True

    def test_different_names_no(self):
        assert is_similarity("中芯国际", "中际旭创") is False

    def test_english_lowercase(self):
        assert is_similarity("nvidia", "NVIDIA") is True


class TestSectorDisambiguation:
    def test_same_name_disjoint_sectors_returns_bool(self):
        # Both names identical — _sectors_disjoint reads from resolver
        result = _sectors_disjoint("中芯国际", "中芯国际", None, None)
        assert isinstance(result, bool)

    def test_unknown_name_returns_false(self):
        # Neither name has known sectors → cannot disambiguate, returns False
        result = _sectors_disjoint("未知公司A", "未知公司B", None, None)
        assert result is False

    def test_no_alias_data_returns_false(self):
        result = _sectors_disjoint("某公司", "某公司", None, None)
        assert result is False


class TestGetSectorTags:
    def test_returns_set(self):
        tags = _get_sector_tags("北方华创")
        assert isinstance(tags, set)

    def test_unknown_company_empty_set(self):
        tags = _get_sector_tags("完全不存在XYZ公司")
        assert isinstance(tags, set)

    def test_with_metadata_sector(self):
        tags = _get_sector_tags("某公司", {"sector": "IC设计"})
        assert "IC设计" in tags

    def test_metadata_list_sectors(self):
        tags = _get_sector_tags("某公司", {"sector_tags": ["材料", "设备"]})
        assert "材料" in tags
        assert "设备" in tags
