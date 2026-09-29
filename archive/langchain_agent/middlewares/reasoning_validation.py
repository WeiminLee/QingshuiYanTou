"""
ReasoningValidationMiddleware — 推理验证中间件

在 LLM 输出后，检查推理质量：
- 检测无来源断言（"市场认为"/"预期"/"应该"等模糊表述）
- 检测数据引用（是否有具体数字、来源引用）
- 生成验证报告（log warning 级别）

设计：
- after_model 钩子（在 LoopDetection 之后）
- 不修改 LLM 输出，仅记录
- 轻量正则匹配，不调用 LLM
"""

from __future__ import annotations

import logging
import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

# ── 无来源断言检测 ─────────────────────────────────────────────────

_UNSUPPORTED_PATTERNS = [
    re.compile(r"市场认为[，,]?", re.IGNORECASE),
    re.compile(r"市场预期[，,]?", re.IGNORECASE),
    re.compile(r"市场普遍[，,]?", re.IGNORECASE),
    re.compile(r"一般认为[，,]?", re.IGNORECASE),
    re.compile(r"预计[会将会]?", re.IGNORECASE),
    re.compile(r"应该[会能]?", re.IGNORECASE),
    re.compile(r"可能[会能]?", re.IGNORECASE),
    re.compile(r"大概率[会]?", re.IGNORECASE),
    re.compile(r"有望[实现达到]?", re.IGNORECASE),
    re.compile(r"或将[达到突破]?", re.IGNORECASE),
]

# ── 数据引用检测 ───────────────────────────────────────────────────

_DATA_REF_PATTERNS = [
    re.compile(r"\d+\.?\d*%"),  # 百分比
    re.compile(r"\d+\.?\d*[万亿千百]"),  # 数量级
    re.compile(r"PE|PB|ROE|EPS|营收|净利|毛利率"),  # 财务指标
    re.compile(r"来源[：:]"),  # 来源标注
    re.compile(r"根据[《\"].*?[》\"]"),  # 引用文档
    re.compile(r"研报|公告|年报|季报"),  # 信息源
]


class ReasoningValidationMiddleware(AgentMiddleware):
    """
    推理验证中间件：检测无支撑断言和数据引用缺失。

    工作流：
    1. 检测 LLM 输出中的无来源断言
    2. 检测是否有数据引用
    3. 生成验证报告（log warning）
    4. 不修改输出

    注意：这是轻量级验证，不调用 LLM。
    """

    name: str = "reasoning_validation"

    def __init__(self, enabled: bool = True):
        super().__init__()
        self._enabled = enabled

    def after_model_hook(self, state: dict, response: AIMessage) -> AIMessage:
        """after_model 钩子：检测推理质量"""
        if not self._enabled:
            return response

        content = response.content
        if not content or not isinstance(content, str):
            return response

        # 检测无来源断言
        unsupported = self._detect_unsupported_claims(content)

        # 检测数据引用
        has_data_refs = self._has_data_references(content)

        # 生成验证报告
        if unsupported or not has_data_refs:
            report_parts = []
            if unsupported:
                report_parts.append(f"无支撑断言({len(unsupported)}): {'; '.join(unsupported[:5])}")
            if not has_data_refs:
                report_parts.append("缺少数据引用")
            report = " | ".join(report_parts)
            logger.warning(f"[ReasoningValidation] {report}")
        else:
            logger.debug("[ReasoningValidation] 推理质量良好：有数据引用，无模糊断言")

        return response  # 不修改输出

    def _detect_unsupported_claims(self, text: str) -> list[str]:
        """检测无来源断言"""
        claims: list[str] = []
        seen = set()
        for pattern in _UNSUPPORTED_PATTERNS:
            for match in pattern.finditer(text):
                match.group(0)
                # 取上下文（前后各 10 字符）
                start = max(0, match.start() - 10)
                end = min(len(text), match.end() + 10)
                context = text[start:end].strip()
                if context not in seen:
                    seen.add(context)
                    claims.append(context)
        return claims

    def _has_data_references(self, text: str) -> bool:
        """检测是否有数据引用"""
        for pattern in _DATA_REF_PATTERNS:
            if pattern.search(text):
                return True
        return False
