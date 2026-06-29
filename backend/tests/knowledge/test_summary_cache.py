"""
test_summary_cache.py — 分层摘要缓存集成测试

覆盖范围：
- 缓存 key 确定性
- 读写 + 过期检测
- 失效传播（Product→L2→L3）
- Company 失效通过 mock Neo4j 传播到 L2/L3
- invalidation trigger 模块
- SummarizeTool async 模式
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestSummaryCache:
    """摘要缓存读写 + 失效传播测试"""

    @pytest.mark.asyncio
    async def test_cache_key_deterministic(self):
        """验证缓存 key 生成是确定性的"""
        from app.knowledge.summary_cache import cache_key

        assert cache_key(1, "C:300308") == "summary:L1:C:300308"
        assert cache_key(2, "P:ABCD1234") == "summary:L2:P:ABCD1234"
        assert cache_key(3, "P:ABCD1234", depth=3) == "summary:L3:P:ABCD1234:3"

    @pytest.mark.asyncio
    async def test_put_and_get_summary(self):
        """验证缓存写入和读取"""
        from app.knowledge.summary_cache import get_summary, put_summary

        await put_summary(
            level=1,
            entity_id="C:TEST001",
            summary="测试公司画像摘要",
            entity_name="测试公司",
            entity_count=10,
        )

        cached = await get_summary(1, "C:TEST001")
        assert cached is not None
        assert cached["summary"] == "测试公司画像摘要"
        assert cached["entity_name"] == "测试公司"
        assert cached["level"] == 1
        assert cached["stale"] is False

    @pytest.mark.asyncio
    async def test_invalidation_product_propagation(self):
        """验证 Product 级失效传播: L2→L3"""
        from app.knowledge.summary_cache import (
            invalidate_entity,
            is_stale,
            put_summary,
        )

        await put_summary(level=2, entity_id="P:TEST002", summary="L2", entity_name="T")
        await put_summary(level=3, entity_id="P:TEST002", summary="L3", entity_name="T", depth=3)

        await invalidate_entity("P:TEST002")

        assert await is_stale(2, "P:TEST002")
        assert await is_stale(3, "P:TEST002", depth=3)

    @pytest.mark.asyncio
    async def test_invalidation_company_l1_only(self):
        """验证 Company 级失效标记 L1"""
        from app.knowledge.summary_cache import (
            invalidate_entity,
            is_stale,
            put_summary,
        )

        await put_summary(level=1, entity_id="C:TEST003", summary="L1", entity_name="T")
        await invalidate_entity("C:TEST003")
        assert await is_stale(1, "C:TEST003")

    @pytest.mark.asyncio
    async def test_company_invalidation_with_mock_lookup(self):
        """验证 Company 失效时，通过 Neo4j 查询关联 Product 并传播到 L2/L3"""
        from app.knowledge.summary_cache import (
            invalidate_entity,
            is_stale,
            put_summary,
        )

        await put_summary(level=1, entity_id="C:TEST004", summary="L1", entity_name="T")
        await put_summary(level=2, entity_id="P:RELATED01", summary="L2", entity_name="T")
        await put_summary(level=3, entity_id="P:RELATED01", summary="L3", entity_name="T", depth=3)

        with patch(
            "app.knowledge.summary_cache._find_related_products",
            AsyncMock(return_value=["P:RELATED01"]),
        ):
            await invalidate_entity("C:TEST004")

        assert await is_stale(1, "C:TEST004")
        assert await is_stale(2, "P:RELATED01")
        assert await is_stale(3, "P:RELATED01", depth=3)

    @pytest.mark.asyncio
    async def test_get_summary_miss(self):
        """验证缓存未命中返回 None"""
        from app.knowledge.summary_cache import get_summary

        result = await get_summary(1, "C:NONEXISTENT")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidator_module(self):
        """验证 summary_invalidator 模块的 collect_affected_entities"""
        from app.knowledge.summary_invalidator import collect_affected_entities

        entity_ids = ["C:300308"]
        written_rels = [
            {"from": "C:300308", "to": "P:800G"},
            {"from": "P:800G", "to": "P:CHIP01"},
        ]

        affected = await collect_affected_entities(entity_ids, written_rels)
        assert "C:300308" in affected
        assert "P:800G" in affected
        assert "P:CHIP01" in affected

    @pytest.mark.asyncio
    async def test_invalidator_trigger_empty(self):
        """验证 trigger_invalidation 在空输入时无副作用"""
        from app.knowledge.summary_invalidator import trigger_invalidation

        await trigger_invalidation([], [])
        await trigger_invalidation(None, None)  # type: ignore


class TestSummarizeTool:
    """SummarizeTool 工具测试（验证 async 模式）"""

    @pytest.mark.asyncio
    async def test_tool_validation_errors(self):
        """验证参数校验"""
        from app.reasoning.tools.knowledge.summarize import summarize

        assert "无效的层级" in summarize._run("C:TEST", level=4)
        assert "请先用 resolve" in summarize._run("", level=1)
        assert "无效的层级" in await summarize._arun("C:TEST", level=0)

    @pytest.mark.asyncio
    async def test_tool_inherits_structured_tool(self):
        """验证工具继承自 StructuredTool（兼容 LangChain）"""
        from langchain_core.tools import StructuredTool
        from app.reasoning.tools.knowledge.summarize import summarize

        assert isinstance(summarize, StructuredTool)
        assert summarize.name == "summarize"
        assert summarize.description
