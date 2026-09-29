"""
fetch_evidence — L1 evidence retrieval tool.

Allows the Agent to trace any conclusion back to the original
source text stored in MongoDB's kg_evidence collection.
"""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool

# 单条证据正文截断上限（字符）。见 _format_evidence 说明。
_MAX_EVIDENCE_TEXT = 8000

logger = logging.getLogger(__name__)


@tool("fetch_evidence")
def fetch_evidence(
    evidence_id: Annotated[
        str,
        "证据 ID，格式为 EV:xxxx（来自知识图谱关系的 evidence_id 属性）",
    ],
) -> str:
    """
    追溯知识图谱中任意结论的原始证据（L1 证据原子层）。

    使用场景：
    - Agent 从 L3 叙事层得到一个定量结论（如"中际旭创 2024 年营收 130 亿"）
    - 需要验证这个结论来自哪份公告/研报的哪一段原文
    - 调用本工具，传入关系的 evidence_id，获取原始文本+来源元数据

    Returns:
        格式化的证据文本，包含原始内容、来源类型、发布时间、置信度
    """
    try:
        from app.knowledge.evidence_service import EvidenceService
        from app.reasoning.tools._async_runner import run_async

        svc = EvidenceService()
        # 统一走 run_async（隔离 loop + NullPool engine / 一次性 mongo client）。
        # 历史实现在已有 running loop 时复用主 loop 跑 coroutine，必报
        # 'Task attached to a different loop'（agent 路径实测）。
        result = run_async(svc.get_evidence(evidence_id))
        return _format_evidence(result)
    except Exception as e:
        logger.warning("fetch_evidence 失败 [%s]: %s", evidence_id, e)
        return f"证据查询失败: {e}"


def _format_evidence(doc: dict | None) -> str:
    """格式化证据文档为 Agent 可读文本。

    长文截断：单条 evidence 的 text_excerpt 最大可达 67 万字符（≈17 万 token，
    实测年报/公告切片）。若不截断，多次 fetch_evidence 会撑爆 LLM 上下文
    （>1M token 报 400 并被反复重试 → 请求挂死 15 分钟）。故截断 + 提示溯源。
    """
    if not doc:
        return "未找到该证据记录（可能 evidence_id 无效或数据已过期）。"

    text = doc.get("text_excerpt", "(无文本内容)") or "(无文本内容)"
    if len(text) > _MAX_EVIDENCE_TEXT:
        text = (
            text[:_MAX_EVIDENCE_TEXT]
            + f"\n...[原文过长已截断：共 {len(text)} 字符，仅显示前 "
            f"{_MAX_EVIDENCE_TEXT} 字符；如需更多请用 backlinks 缩小范围或换成更精确的证据 ID]"
        )

    lines = [
        f"证据 ID: {doc.get('evidence_id', 'N/A')}",
        f"来源类型: {doc.get('source_type', 'N/A')}",
        f"来源名称: {doc.get('source_name', 'N/A')}",
        f"发布时间: {doc.get('publish_date', 'N/A')}",
        f"置信度: {doc.get('confidence', 'N/A')}",
        "--- 原始文本 ---",
        text,
    ]

    subject = doc.get("subject_hint") or {}
    if subject.get("ts_code"):
        lines.insert(2, f"关联股票: {subject['ts_code']}")

    return "\n".join(lines)
