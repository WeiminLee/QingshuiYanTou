"""
LangChain Agent — V2.0 Agent 引擎

目录结构：
- lead_agent.py: LeadAgentConfig dataclass
- prompts/lead_system_prompt.py: system prompt 生成器
- middlewares/: DeerFlow 风格中间件
- client.py: SSE 桥接层（run_lead_agent 主入口）
- integrations.py: HarnessConfig 集成配置
"""

from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template

__all__ = [
    "apply_prompt_template",
]
