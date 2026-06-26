"""
fetch_evidence — L1 evidence retrieval tool.

Allows the Agent to trace any conclusion back to the original
source text stored in MongoDB's kg_evidence collection.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from langchain_core.tools import tool

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

        svc = EvidenceService()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(svc.get_evidence(evidence_id))
            loop.close()
            return _format_evidence(result)

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(lambda: loop.run_until_complete(svc.get_evidence(evidence_id)))
            result = future.result(timeout=10)
        return _format_evidence(result)
    except Exception as e:
        logger.warning("fetch_evidence 失败 [%s]: %s", evidence_id, e)
        return f"证据查询失败: {e}"


def _format_evidence(doc: dict | None) -> str:
    """格式化证据文档为 Agent 可读文本。"""
    if not doc:
        return "未找到该证据记录（可能 evidence_id 无效或数据已过期）。"

    lines = [
        f"证据 ID: {doc.get('evidence_id', 'N/A')}",
        f"来源类型: {doc.get('source_type', 'N/A')}",
        f"来源名称: {doc.get('source_name', 'N/A')}",
        f"发布时间: {doc.get('publish_date', 'N/A')}",
        f"置信度: {doc.get('confidence', 'N/A')}",
        "--- 原始文本 ---",
        doc.get("text_excerpt", "(无文本内容)"),
    ]

    subject = doc.get("subject_hint") or {}
    if subject.get("ts_code"):
        lines.insert(2, f"关联股票: {subject['ts_code']}")

    return "\n".join(lines)
