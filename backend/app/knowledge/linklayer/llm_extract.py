# backend/app/knowledge/linklayer/llm_extract.py
"""LLM 浅提取（spec §4.2）：类型受约束关键字提取。单次调用、扁平输出、可缓存。

铁律：LLM 只输出 surface form，不做归一化/推理/改写。
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from app.config import settings
from app.core.llm_client import chat_async

logger = logging.getLogger(__name__)

KEYWORD_PROMPT_VERSION = "kw_v2"  # v2: 抽取窗口 6000→12000（长 evidence 尾部 scope 召回）
LLM_INPUT_MAX_CHARS = 12_000  # 浅提取语料窗口（96.4% evidence 全文覆盖）
# 极重要：版本号变更会使 keyword_extraction 缓存全量失效——LLM 回填在全量跑完后
# 由 v2 重放一遍（skip-llm 词典层不受影响，链接幂等）。

KEYWORD_SYSTEM_PROMPT = """你是投研文本的关键字标注器。从用户给出的文本中提取三类关键字，只输出原文出现过的表述：
- COMPANY: 公司名（上市/非上市/境外均算）
- PRODUCT: 产品、技术、产线、材料名
- METRIC: 指标名（如带数值，输出 {"name","value","unit","period"}）

规则：保留原文表述不改写（"8英寸抛光硅片"不得缩写为"硅片"）；
不提取行业泛称（公司、行业、产品、客户等）；不确定的不提取。
只输出 JSON，格式：{"company": [...], "product": [...], "metric": [...]}"""


def parse_llm_json(raw: str) -> dict | None:
    """解析 LLM 输出；失败返回 None（不重试——浅任务不允许重试链）。

    company/product/metric 字段非列表时整体丢弃（防 None / 字符串被逐字符拆分）。
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if raw.startswith("```"):  # 单行 fence：```json {...}```
            raw = raw[3:].strip()
            if raw[:4].lower() == "json":
                raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    company = data.get("company")
    product = data.get("product")
    metric = data.get("metric")
    return {
        "company": [str(x) for x in company[:20]] if isinstance(company, list) else [],
        "product": [str(x) for x in product[:20]] if isinstance(product, list) else [],
        "metric": [m for m in metric[:20] if isinstance(m, dict) and m.get("name")]
        if isinstance(metric, list)
        else [],
    }


async def extract_keywords(evidence: dict, *, use_cache: bool = True) -> dict | None:
    """对单条 evidence 做关键字浅提取。结果写回 Mongo `keyword_extraction` 字段缓存。"""
    cached = evidence.get("keyword_extraction") or {}
    if use_cache and cached.get("version") == KEYWORD_PROMPT_VERSION:
        cached_result = cached.get("result")
        if cached_result is not None:  # result 缺失视为缓存未命中，走重新提取
            return cached_result

    from app.knowledge.evidence_service import EvidenceService  # 延迟导入避免循环

    # 抽取语料窗口（spec §4.2）：覆盖 96.4% evidence 全文；
    # 超长 evidence（整章大年报等 6.7% 长尾）尾部仍会截断，由词表治理与重切分兜底
    text = (evidence.get("text_excerpt") or "")[:LLM_INPUT_MAX_CHARS]
    result: dict | None = None
    if text.strip():
        try:
            # chat_async 只收单个 prompt（内部组装 user message），返回 str；
            # stream=True 绕过网关 60s 无数据超时，写法参照 rag_extractor._call_llm_async
            resp = await chat_async(
                f"{KEYWORD_SYSTEM_PROMPT}\n\n{text}",
                model=settings.llm_extraction_model,
                temperature=0.0,
                stream=True,
            )
            result = parse_llm_json(resp)
        except Exception:
            logger.exception("keyword extraction failed for %s", evidence.get("evidence_id"))
            return None

    if result is not None:
        svc = EvidenceService()
        await svc.update_keyword_extraction(
            evidence["evidence_id"],
            {"version": KEYWORD_PROMPT_VERSION, "result": result,
             "extracted_at": datetime.now(UTC).isoformat()},
        )
    return result
