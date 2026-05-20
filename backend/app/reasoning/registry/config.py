"""
ToolConfig — Pydantic 配置模型

定义工具的 YAML 配置结构，参考 DeerFlow tools/tool_config.py。
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ToolGroup(str, Enum):
    """工具分组枚举（与 config.yaml groups 一致）"""
    MARKET_DATA = "market_data"      # K线、板块热度、市场宽度
    KNOWLEDGE = "knowledge"          # 知识图谱、研报、公告
    SEARCH = "search"               # 联网搜索/抓取
    FINANCIAL = "financial"          # 财务数据、互动易
    CHART = "chart"                 # 可视化图表
    AGENT = "agent"                 # Agent 控制工具（write_todos）
    FILE = "file"                   # 文件操作（ls/read_file/write_file）
    CLARIFICATION = "clarification" # 澄清拦截（ask_clarification）


class ToolConfig(BaseModel):
    """
    单个工具的配置（对应 YAML 中的一个 entry）。

    用于 YAML 配置驱动注册，也可在代码中直接构造。
    """

    name: str = Field(..., description="工具唯一标识（函数名）")
    group: ToolGroup = Field(..., description="工具所属分组")
    use: str = Field(..., description="工具函数路径，如 app.reasoning.tools.market_data.kline.get_kline")
    description: str = Field(default="", description="工具描述（展示给 LLM）")
    enabled: bool = Field(default=True, description="是否启用")
    variables: dict[str, str] = Field(
        default_factory=dict,
        description="工具级别环境变量映射（覆盖全局）",
    )

    model_config = {"use_enum_values": True}


class ToolConfigList(BaseModel):
    """YAML 根配置"""
    tools: list[ToolConfig] = Field(default_factory=list)
