"""
YAML 配置加载器（DeerFlow 风格）

从 config.yaml 加载工具配置，并通过 resolve_variable 动态导入工具实例。
参考 DeerFlow tools/loader.py 的 resolve_variable 模式。

支持：
- config.yaml 声明式工具注册（优先）
- 内嵌默认配置（fallback）
- 传入 ToolConfig 列表直接使用
- 环境变量插值：$VAR / ${VAR}
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.reasoning.registry.config import ToolConfig, ToolConfigList, ToolGroup
from app.reasoning.registry.registry import ToolRegistry, get_registry
from app.reasoning.registry.resolve_variable import resolve_variable

logger = logging.getLogger(__name__)

# 配置文件路径（相对于本文件所在目录）
_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _build_default_config() -> list[ToolConfig]:
    """
    内嵌默认工具配置（无 YAML 文件时的 fallback）。

    所有路径指向 app.reasoning.tools 下的 @tool 装饰函数。
    新增工具（web_fetch/ls/read_file/write_file/ask_clarification）需要先创建对应文件。
    """
    return [
        # ── market_data ──────────────────────────────
        ToolConfig(
            name="get_kline",
            group=ToolGroup.MARKET_DATA,
            use="app.reasoning.tools.market_data.kline:get_kline",
            description="获取股票K线数据和技术指标（MACD/RSI/BOLL/MA），用于判断技术面趋势",
        ),
        ToolConfig(
            name="get_concept_hot",
            group=ToolGroup.MARKET_DATA,
            use="app.reasoning.tools.market_data.concept_hot:get_concept_hot",
            description="获取概念板块热度排名，包括涨跌幅度、成交量、涨停家数等",
        ),
        ToolConfig(
            name="get_market_breadth",
            group=ToolGroup.MARKET_DATA,
            use="app.reasoning.tools.market_data.market_breadth:get_market_breadth",
            description="获取市场宽度指标，包括上涨下跌家数、涨停炸板数量、市场情绪等",
        ),
        # ── knowledge ────────────────────────────────
        ToolConfig(
            name="neo4j_traverse",
            group=ToolGroup.KNOWLEDGE,
            use="app.reasoning.tools.knowledge.neo4j:neo4j_traverse",
            description="查询知识图谱中实体间的关系（1-hop 或 2-hop 传导链），支持 V2 RELATES 边",
        ),
        ToolConfig(
            name="neo4j_entity_info",
            group=ToolGroup.KNOWLEDGE,
            use="app.reasoning.tools.knowledge.neo4j:neo4j_entity_info",
            description="查询知识图谱中实体的详细属性（行业状态、信号、置信度、别名等）",
        ),
        ToolConfig(
            name="neo4j_path",
            group=ToolGroup.KNOWLEDGE,
            use="app.reasoning.tools.knowledge.neo4j:neo4j_path",
            description="查询两个实体之间的传导路径（供应链、产业链等）",
        ),
        ToolConfig(
            name="neo4j_industry_state",
            group=ToolGroup.KNOWLEDGE,
            use="app.reasoning.tools.knowledge.neo4j:neo4j_industry_state",
            description="查询行业内各公司的生命周期状态分布和信号",
        ),
        ToolConfig(
            name="neo4j_kg_search",
            group=ToolGroup.KNOWLEDGE,
            use="app.reasoning.tools.knowledge.neo4j:neo4j_kg_search",
            description="知识图谱智能搜索：根据自然语言查询，自动选择实体搜索、关系搜索或路径搜索策略，返回相关性排序的结果",
        ),
        ToolConfig(
            name="get_research_report",
            group=ToolGroup.KNOWLEDGE,
            use="app.reasoning.tools.knowledge.research_report:get_research_report",
            description="检索研报摘要，包括券商评级、目标价、核心观点等",
        ),
        ToolConfig(
            name="get_announcement",
            group=ToolGroup.KNOWLEDGE,
            use="app.reasoning.tools.knowledge.announcement:get_announcement",
            description="检索上市公司公告，查看重要事件披露",
        ),
        # ── search ──────────────────────────────────
        ToolConfig(
            name="tavily_search",
            group=ToolGroup.SEARCH,
            use="app.reasoning.tools.search.tavily:tavily_search",
            description="联网搜索实时市场信息、新闻、政策动态",
        ),
        # ── financial ────────────────────────────────
        ToolConfig(
            name="get_stock_profile",
            group=ToolGroup.FINANCIAL,
            use="app.reasoning.tools.financial.profile:get_stock_profile",
            description="查询股票主营业务概况，包括主营产品、经营范围",
        ),
        ToolConfig(
            name="get_irm",
            group=ToolGroup.FINANCIAL,
            use="app.reasoning.tools.financial.irm:get_irm",
            description="查询互动易 Q&A 数据，了解投资者与公司的交流内容",
        ),
        # ── chart ──────────────────────────────────
        ToolConfig(
            name="present_chart",
            group=ToolGroup.CHART,
            use="app.reasoning.tools.chart:present_chart",
            description="渲染交互式图表（ECharts）：K线图/板块热度/雷达图/桑基图",
        ),
        # ── agent ──────────────────────────────────
        ToolConfig(
            name="write_todos",
            group=ToolGroup.AGENT,
            use="app.reasoning.langchain_agent.tools.todo:write_todos",
            description="更新待办列表状态（plan mode 下用于记录分析步骤进度）",
        ),
        # ── clarification ──────────────────────────
        ToolConfig(
            name="ask_clarification",
            group=ToolGroup.CLARIFICATION,
            use="app.reasoning.tools.builtins.clarification:ask_clarification",
            description="向用户提问以澄清需求或获取必要信息",
        ),
        # ── search (extended) ──────────────────────
        ToolConfig(
            name="web_fetch",
            group=ToolGroup.SEARCH,
            use="app.reasoning.tools.search.web_fetch:web_fetch",
            description="抓取网页正文内容，返回 Markdown 格式纯净文本",
        ),
        # ── file ──────────────────────────────────
        ToolConfig(
            name="ls",
            group=ToolGroup.FILE,
            use="app.reasoning.tools.sandbox.file_tools:ls_tool",
            description="列出目录内容（最多2层深度，树状格式）",
        ),
        ToolConfig(
            name="read_file",
            group=ToolGroup.FILE,
            use="app.reasoning.tools.sandbox.file_tools:read_file_tool",
            description="读取文本文件内容，支持行范围截取",
        ),
        ToolConfig(
            name="write_file",
            group=ToolGroup.FILE,
            use="app.reasoning.tools.sandbox.file_tools:write_file_tool",
            description="写入或追加内容到文本文件",
        ),
    ]


def load_tools_from_config(configs: list[ToolConfig] | None = None) -> list[ToolConfig]:
    """
    加载并注册工具。

    优先级：
    1. 传入 configs 参数 → 直接使用
    2. config.yaml 存在 → 从 YAML 加载（环境变量自动展开）
    3. 否则 → 内嵌默认配置

    每个工具通过 resolve_variable(use) 动态导入，import 失败记录警告但不阻断。
    """
    registry = get_registry()
    registry.clear()

    # 确定配置来源
    if configs is not None:
        tool_configs = configs
        source = "provided list"
    elif _CONFIG_PATH.exists():
        import yaml

        with open(_CONFIG_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        cfg_list = ToolConfigList(**raw)
        tool_configs = cfg_list.tools
        source = f"YAML ({_CONFIG_PATH})"
    else:
        tool_configs = _build_default_config()
        source = "built-in defaults"

    logger.info(f"[Registry] Loading {len(tool_configs)} tools from {source}")

    # 注册工具名称集合（用于去重检查）
    seen_names: set[str] = set()
    registered = 0
    skipped = 0

    for cfg in tool_configs:
        if not cfg.enabled:
            logger.debug(f"[Registry] Skipping disabled tool: {cfg.name}")
            skipped += 1
            continue

        if cfg.name in seen_names:
            logger.warning(f"[Registry] Duplicate tool name '{cfg.name}' in config, skipping")
            continue
        seen_names.add(cfg.name)

        try:
            instance = resolve_variable(cfg.use)
        except ImportError as e:
            logger.warning(f"[Registry] Tool '{cfg.name}' import failed ({cfg.use}): {e}, skipping")
            continue

        registry.register(cfg, instance)
        registered += 1

    logger.info(
        f"[Registry] Loaded {registered}/{len(tool_configs)} tools "
        f"({skipped} disabled, {len(tool_configs) - registered - skipped} failed)"
    )
    return registry.get_configs()
