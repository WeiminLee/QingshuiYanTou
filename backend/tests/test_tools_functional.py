"""
test_tools_functional.py — 工具功能测试

测试所有 Agent 工具的导入、调用和返回格式。
对于需要网络/云端 API 的工具，使用 mock 避免外部依赖。
"""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 工具导入测试 ──────────────────────────────────────────────────────────────

class TestToolImports:
    """验证所有工具能正确导入"""

    def test_import_kline_tool(self):
        """get_kline 工具导入"""
        from app.reasoning.tools.market_data.kline.kline import get_kline
        assert get_kline is not None
        assert get_kline.name == "get_kline"

    def test_import_concept_hot_tool(self):
        """get_concept_hot 工具导入"""
        from app.reasoning.tools.market_data.concept_hot import get_concept_hot
        assert get_concept_hot is not None
        assert get_concept_hot.name == "get_concept_hot"

    def test_import_neo4j_tools(self):
        """neo4j 工具集导入"""
        from app.reasoning.tools.knowledge.neo4j.neo4j import (
            neo4j_traverse,
            neo4j_entity_info,
            neo4j_path,
            neo4j_industry_state,
        )
        assert neo4j_traverse.name == "neo4j_traverse"
        assert neo4j_entity_info.name == "neo4j_entity_info"
        assert neo4j_path.name == "neo4j_path"
        assert neo4j_industry_state.name == "neo4j_industry_state"

    def test_import_research_report_tool(self):
        """get_research_report 工具导入"""
        from app.reasoning.tools.knowledge.research_report import get_research_report
        assert get_research_report is not None
        assert get_research_report.name == "get_research_report"

    def test_import_announcement_tool(self):
        """get_announcement 工具导入"""
        from app.reasoning.tools.knowledge.announcement import get_announcement
        assert get_announcement is not None
        assert get_announcement.name == "get_announcement"

    def test_import_tavily_tool(self):
        """tavily_search 工具导入"""
        from app.reasoning.tools.search.tavily.tavily import tavily_search
        assert tavily_search is not None
        assert tavily_search.name == "tavily_search"

    def test_import_web_fetch_tool(self):
        """web_fetch 工具导入"""
        from app.reasoning.tools.search.web_fetch import web_fetch
        assert web_fetch is not None
        assert web_fetch.name == "web_fetch"

    def test_import_stock_profile_tool(self):
        """get_stock_profile 工具导入"""
        from app.reasoning.tools.financial.profile.profile import get_stock_profile
        assert get_stock_profile is not None
        assert get_stock_profile.name == "get_stock_profile"

    def test_import_irm_tool(self):
        """get_irm 工具导入"""
        from app.reasoning.tools.financial.irm import get_irm
        assert get_irm is not None
        assert get_irm.name == "get_irm"

    def test_import_present_chart_tool(self):
        """present_chart 工具导入"""
        from app.reasoning.tools.chart import present_chart
        assert present_chart is not None
        assert present_chart.name == "present_chart"

    def test_import_file_tools(self):
        """sandbox 文件工具导入"""
        from app.reasoning.tools.sandbox.file_tools import ls_tool, read_file_tool, write_file_tool
        assert ls_tool.name == "ls"
        assert read_file_tool.name == "read_file"
        assert write_file_tool.name == "write_file"

    def test_import_clarification_tool(self):
        """ask_clarification 工具导入"""
        from app.reasoning.tools.builtins.clarification import ask_clarification
        assert ask_clarification is not None
        assert ask_clarification.name == "ask_clarification"


# ── 市场数据工具测试 ──────────────────────────────────────────────────────────

class TestMarketDataTools:
    """市场数据工具功能测试"""

    @patch("app.reasoning.tools.market_data.kline.kline.get_http_session")
    def test_get_kline_success(self, mock_session):
        """get_kline 正常返回K线数据"""
        from app.reasoning.tools.market_data.kline.kline import get_kline

        # Mock API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {"trade_date": "20240501", "close": 50.0, "open": 49.0, "high": 51.0, "low": 48.5,
                 "volume": 1000000, "pct_chg": 2.04, "qfq_factor": 1.0},
                {"trade_date": "20240502", "close": 51.5, "open": 50.0, "high": 52.0, "low": 49.5,
                 "volume": 1200000, "pct_chg": 3.0, "qfq_factor": 1.0},
            ]
        }
        mock_session.return_value.get.return_value = mock_response

        result = get_kline.invoke({
            "ts_code": "300308.SZ",
            "start_date": "20240501",
            "end_date": "20240502",
        })

        assert "K线" in result
        assert "300308.SZ" in result
        assert "日线" in result
        assert "51.50" in result or "51.5" in result

    def test_get_kline_without_params(self):
        """get_kline 不传参数应使用默认值"""
        from app.reasoning.tools.market_data.kline.kline import get_kline

        # Mock 时间函数，避免实际调用
        with patch("app.reasoning.tools.market_data.kline.kline.get_http_session") as mock_session:
            mock_response = MagicMock()
            mock_response.json.return_value = {"items": []}
            mock_session.return_value.get.return_value = mock_response

            result = get_kline.invoke({"ts_code": "000001.SZ"})
            assert "K线" in result

    @patch("app.reasoning.tools.market_data.concept_hot.get_http_session")
    def test_get_concept_hot_success(self, mock_session):
        """get_concept_hot 正常返回板块热度"""
        from app.reasoning.tools.market_data.concept_hot import get_concept_hot

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {"name": "光通信", "change_pct": 5.5, "turnover": 3.2, "limit_up_count": 3, "volume": 50000000},
                {"name": "AI算力", "change_pct": -2.1, "turnover": 8.5, "limit_up_count": 0, "volume": 80000000},
            ]
        }
        mock_session.return_value.get.return_value = mock_response

        result = get_concept_hot.invoke({"top_n": 10, "sort_by": "change_pct"})

        assert "概念板块" in result
        assert "光通信" in result
        assert "AI算力" in result
        assert "5.50%" in result or "5.5%" in result


# ── 知识图谱工具测试 ──────────────────────────────────────────────────────────

class TestNeo4jTools:
    """Neo4j 知识图谱工具测试（使用 mock）"""

    def test_neo4j_traverse_handles_exception(self):
        """neo4j_traverse 异常处理"""
        from app.reasoning.tools.knowledge.neo4j.neo4j import neo4j_traverse

        # 直接测试，当 Neo4j 不可用时返回友好错误
        result = neo4j_traverse.invoke({"entity": "华为"})
        # 应该返回错误信息或结果
        assert isinstance(result, str)
        assert len(result) > 0

    def test_neo4j_entity_info_handles_exception(self):
        """neo4j_entity_info 异常处理"""
        from app.reasoning.tools.knowledge.neo4j.neo4j import neo4j_entity_info

        result = neo4j_entity_info.invoke({"entity": "华为"})
        assert isinstance(result, str)

    def test_neo4j_path_handles_exception(self):
        """neo4j_path 异常处理"""
        from app.reasoning.tools.knowledge.neo4j.neo4j import neo4j_path

        result = neo4j_path.invoke({"start": "公司A", "end": "公司B"})
        assert isinstance(result, str)

    def test_neo4j_industry_state_handles_exception(self):
        """neo4j_industry_state 异常处理"""
        from app.reasoning.tools.knowledge.neo4j.neo4j import neo4j_industry_state

        result = neo4j_industry_state.invoke({"industry": "光通信"})
        assert isinstance(result, str)


# ── 研报与公告工具测试 ───────────────────────────────────────────────────────

class TestResearchTools:
    """研报与公告工具测试"""

    @patch("app.reasoning.tools.knowledge.research_report.get_http_session")
    def test_get_research_report_no_data(self, mock_session):
        """get_research_report 无数据时"""
        from app.reasoning.tools.knowledge.research_report import get_research_report

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_session.return_value.get.return_value = mock_response

        result = get_research_report.invoke({"keyword": "不存在的关键词xyz"})

        assert "未找到" in result

    @patch("app.reasoning.tools.knowledge.research_report.get_http_session")
    def test_get_research_report_with_data(self, mock_session):
        """get_research_report 有数据时"""
        from app.reasoning.tools.knowledge.research_report import get_research_report

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total": 2,
            "items": [
                {
                    "title": "首次覆盖：买入评级",
                    "institution": "中信证券",
                    "analyst": "张三",
                    "rating": "买入",
                    "target_price": "50元",
                    "pub_date": "2024-05-01",
                    "summary": "公司业绩增长良好，目标价50元。",
                }
            ]
        }
        mock_session.return_value.get.return_value = mock_response

        result = get_research_report.invoke({"ts_code": "300308.SZ"})

        assert "研报" in result
        assert "中信证券" in result
        assert "买入" in result

    @patch("app.reasoning.tools.knowledge.announcement.get_http_session")
    def test_get_announcement_no_data(self, mock_session):
        """get_announcement 无数据时"""
        from app.reasoning.tools.knowledge.announcement import get_announcement

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_session.return_value.get.return_value = mock_response

        result = get_announcement.invoke({"keyword": "不存在的公告xyz"})

        assert "未找到" in result


# ── 搜索工具测试 ──────────────────────────────────────────────────────────────

class TestSearchTools:
    """搜索工具测试"""

    def test_tavily_search_returns_string(self):
        """tavily_search 返回字符串"""
        from app.reasoning.tools.search.tavily.tavily import tavily_search

        # 由于 Tavily API 需要真实 key，直接调用测试返回类型
        # 实际使用时 API 调用会返回结果
        result = tavily_search.invoke({"query": "测试"})
        assert isinstance(result, str)
        # 应该返回错误信息（因为没有真实 API key）或结果
        assert len(result) > 0

    def test_web_fetch_invalid_url(self):
        """web_fetch 无效URL时"""
        from app.reasoning.tools.search.web_fetch import web_fetch

        result = web_fetch.invoke({"url": "ftp://example.com"})
        assert "错误" in result


# ── 财务工具测试 ──────────────────────────────────────────────────────────────

class TestFinancialTools:
    """财务工具测试"""

    @patch("app.reasoning.tools.financial.profile.profile.get_http_session")
    def test_get_stock_profile_no_data(self, mock_session):
        """get_stock_profile 无数据时"""
        from app.reasoning.tools.financial.profile.profile import get_stock_profile

        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_session.return_value.get.return_value = mock_response

        result = get_stock_profile.invoke({"ts_code": "999999.XS"})

        assert "未找到" in result

    @patch("app.reasoning.tools.financial.profile.profile.get_http_session")
    def test_get_stock_profile_with_data(self, mock_session):
        """get_stock_profile 有数据时"""
        from app.reasoning.tools.financial.profile.profile import get_stock_profile

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "main_business": "光模块研发生产销售",
            "product_type": "高速光模块",
            "product_name": "400G光模块",
            "business_scope": "光通信设备制造",
        }
        mock_session.return_value.get.return_value = mock_response

        result = get_stock_profile.invoke({"ts_code": "300308.SZ"})

        assert "股票概况" in result
        assert "光模块" in result

    @patch("app.reasoning.tools.market_data._http.get_http_session")
    def test_get_irm_no_data(self, mock_session):
        """get_irm 无数据时"""
        from app.reasoning.tools.financial.irm import get_irm

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_session.return_value.get.return_value = mock_response

        result = get_irm.invoke({"ts_code": "999999.XS"})

        assert "未找到" in result

    @patch("app.reasoning.tools.financial.profile.profile.get_http_session")
    def test_get_irm_with_data(self, mock_session):
        """get_irm 有数据时"""
        from app.reasoning.tools.financial.profile.profile import get_irm

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total": 1,
            "items": [
                {
                    "question": "公司对AI算力的布局如何？",
                    "answer": "公司正在加大AI相关产品研发投入。",
                    "question_time": "2024-05-01",
                    "signals": "AI",
                }
            ]
        }
        mock_session.return_value.get.return_value = mock_response

        result = get_irm.invoke({"ts_code": "300308.SZ"})

        assert "互动易" in result
        assert "AI" in result


# ── 图表工具测试 ──────────────────────────────────────────────────────────────

class TestChartTools:
    """图表工具测试"""

    def test_present_chart_kline(self):
        """present_chart K线图渲染"""
        from app.reasoning.tools.chart import present_chart

        result = present_chart.invoke({
            "chart_type": "kline",
            "data": {
                "ts_code": "300308.SZ",
                "candles": [
                    {"date": "2024-05-01", "open": 50, "close": 52, "high": 53, "low": 49, "vol": 1000},
                    {"date": "2024-05-02", "open": 52, "close": 51, "high": 53, "low": 50, "vol": 1100},
                ],
                "ma5": [None, 51.5],
                "ma10": [None, 51.5],
            },
            "title": "测试K线",
        })

        assert "图表已生成" in result
        assert "kline_" in result
        assert result.endswith(".html")

    def test_present_chart_unknown_type(self):
        """present_chart 未知类型时"""
        from app.reasoning.tools.chart import present_chart

        result = present_chart.invoke({
            "chart_type": "unknown_type_xyz",
            "data": {},
            "title": "测试",
        })

        assert "未知图表类型" in result
        assert "可用" in result

    def test_present_chart_empty_data(self):
        """present_chart 空数据时"""
        from app.reasoning.tools.chart import present_chart

        result = present_chart.invoke({
            "chart_type": "confidence_radar",
            "data": {"indicators": []},
            "title": "测试",
        })

        assert "无" in result or "图表" in result


# ── 工具参数描述测试 ──────────────────────────────────────────────────────────

class TestToolDescriptions:
    """验证工具参数描述是否完整"""

    def test_kline_has_description(self):
        from app.reasoning.tools.market_data.kline.kline import get_kline
        assert hasattr(get_kline, "name")
        assert get_kline.name == "get_kline"

    def test_tavily_has_description(self):
        from app.reasoning.tools.search.tavily.tavily import tavily_search
        assert hasattr(tavily_search, "name")
        assert tavily_search.name == "tavily_search"

    def test_present_chart_has_description(self):
        from app.reasoning.tools.chart import present_chart
        assert hasattr(present_chart, "name")
        assert present_chart.name == "present_chart"


# ── 工具注册表测试 ────────────────────────────────────────────────────────────

class TestToolRegistry:
    """验证工具注册表"""

    def test_registry_exists(self):
        """注册表单例存在"""
        from app.reasoning.registry import get_registry
        registry = get_registry()
        assert registry is not None

    def test_registry_has_basic_methods(self):
        """注册表有基本方法"""
        from app.reasoning.registry import get_registry
        registry = get_registry()
        assert hasattr(registry, "register")
        assert hasattr(registry, "get_tool_instance")
        assert hasattr(registry, "get_tool_instances")
        assert hasattr(registry, "get_enabled_names")

    def test_registry_register_and_get(self):
        """注册表可以注册和获取工具"""
        from app.reasoning.registry import get_registry
        from app.reasoning.tools.market_data.kline.kline import get_kline
        from app.reasoning.registry.config import ToolConfig, ToolGroup

        registry = get_registry()

        # 注册工具
        config = ToolConfig(
            name="get_kline",
            use="app.reasoning.tools.market_data.kline.get_kline",
            group=ToolGroup.MARKET_DATA,
            enabled=True,
        )
        registry.register(config, get_kline)

        # 获取工具
        tool = registry.get_tool_instance("get_kline")
        assert tool is not None
        assert tool.name == "get_kline"


# ── 工具执行器测试 ────────────────────────────────────────────────────────────

class TestToolExecutor:
    """验证工具执行器"""

    def test_executor_can_import(self):
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor
        assert ToolExecutor is not None

    def test_executor_has_retry_strategy(self):
        from app.reasoning.langchain_agent.retry import ExponentialBackoff
        strategy = ExponentialBackoff()
        assert strategy.max_attempts == 3
        assert strategy.base_delay == 1.0

    def test_executor_has_never_parallel(self):
        """NEVER_PARALLEL 常量存在"""
        from app.reasoning.langchain_agent.tool_executor import NEVER_PARALLEL
        # 文件写入类工具必须串行
        assert "write_file" in NEVER_PARALLEL
        assert "clarify" in NEVER_PARALLEL

    def test_executor_has_tool_result(self):
        """ToolResult dataclass 存在"""
        from app.reasoning.langchain_agent.tool_executor import ToolResult
        result = ToolResult(
            tool_name="test",
            success=True,
            result="ok",
            duration_ms=100,
        )
        assert result.success
        assert result.tool_name == "test"

    def test_build_preview_function(self):
        """build_preview 函数存在并工作"""
        from app.reasoning.langchain_agent.tool_executor import build_preview

        # 测试 K线格式
        result = build_preview("get_kline", "股票 300308.SZ K线，共100条")
        assert "100" in result

        # 测试 Tavily 格式
        result = build_preview("tavily_search", "**1.** 标题\n   来源：url")
        assert "找到" in result

    def test_should_parallel_method(self):
        """ToolExecutor._should_parallel 方法存在"""
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        executor = ToolExecutor(tools=[])
        # 验证方法存在
        assert hasattr(executor, "_should_parallel")
