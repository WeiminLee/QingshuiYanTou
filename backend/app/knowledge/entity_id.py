"""
Entity ID 生成模块

负责实体名称规范化、entity_id 生成和公司名称解析。
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """
    实体名称归一化，消除因格式差异导致的重复节点。

    处理：
    1. 全角转半角（（）→()，—— → --，等）
    2. 去除首尾空白
    3. 合并中间多余空格
    4. 去除不可见字符
    """
    if not name:
        return ""
    # 全角转半角
    normalized = unicodedata.normalize("NFKC", name)
    # 去除不可见字符
    normalized = "".join(ch for ch in normalized if ch.isprintable() or ch in "\n\t")
    # 合并多余空格
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def looks_like_ts_code(s: str) -> bool:
    """判断字符串是否为股票代码格式"""
    return bool(s and len(s) >= 8 and "." in s and s.replace(".", "").replace("-", "").isalnum())


def entity_id_from_name(name: str, entity_type: str) -> str:
    """根据实体名称和类型生成 entity_id（不查别名表，归一化后 hash）"""
    name = normalize_name(name)
    h16 = hashlib.md5(name.encode("utf-8")).hexdigest()[:16].upper()
    h12 = h16[:12]
    if entity_type == "Product":
        return f"P:{h16}"
    elif entity_type == "Tech":
        return f"T:{h12}"
    elif entity_type == "Industry":
        return f"IND:{h12}"
    elif entity_type == "Metric":
        return f"M:{h12}"
    elif entity_type == "Event":
        return f"E:UNKNOWN:UNKNOWN:{h16}"
    return f"{entity_type.upper()}:{h12}"


def resolve_company_id(name: str) -> tuple[str, str]:
    """
    解析公司名称 → (entity_id, name)。

    策略：
    1. 规范化名称
    2. 尝试 StockNameResolver（PostgreSQL 主源）
    3. 返回 (entity_id, normalized_name)
    """
    name_clean = normalize_name(name)
    if not name_clean:
        return "CO:UNKNOWN", name
    from app.knowledge.stock_name_resolver import get_stock_name_resolver

    return get_stock_name_resolver().resolve_entity_id(name_clean)


def validate_metric(entity: dict) -> bool:
    """
    验证 Metric 类型实体是否有效。

    Metric 必须同时含数字和单位。
    """
    desc = entity.get("properties", {}).get("description", "")
    if not desc:
        return False
    has_number = bool(re.search(r"\d+[\.\d]*", desc))
    has_unit = bool(
        re.search(
            r"(%|亿元|万元|元|亿|万只|万辆|万吨|万台|万套|件|只|台|套|个|人|天|[0-9]+年|[0-9]+月|个百分点|比率|比例|增速|占比)",
            desc,
        )
    )
    return has_number and has_unit


async def disambiguate_with_llm(
    name: str,
    context: str,
) -> tuple[str, str | None]:
    """
    使用 LLM 消歧公司名称。

    Args:
        name: 待消歧的公司名称
        context: 文档上下文

    Returns:
        (decision, resolved_id) - decision="match"/"new"/"unknown"，resolved_id 为消歧结果
    """
    from app.core.llm_client import chat

    prompt = f"""给定公司名称 "{name}" 和上下文，判断它最可能是哪个上市公司。

上下文：{context[:500]}

请输出 JSON：
{{"decision": "match"/"new"/"unknown", "reason": "...", "resolved_id": "C:xxxxxx.SH 或 null"}}
"""
    try:
        result = await chat(prompt)
        import json

        data = json.loads(result)
        return data.get("decision", "unknown"), data.get("resolved_id")
    except Exception as e:
        logger.debug("LLM 消歧失败 [%s]: %s", name, e)
        return "unknown", None


def build_name_to_id_map(
    merged_entities: list[dict],
    ts_code: str,
    disambiguation_context: str = "",
) -> dict[str, str]:
    """
    从实体列表构建 name → entity_id 映射（同步版本）。

    Company 实体优先用 ts_code 格式，否则用 hash。
    名称统一归一化，消除同一实体不同写法的重复节点。

    注意：此函数不支持 LLM 消歧（需要异步上下文）。
    如需 LLM 消歧，请使用 build_name_to_id_map_async。
    """
    lookup: dict[str, str] = {}
    for e in merged_entities:
        name_raw = e.get("entity_name", "").strip()
        if not name_raw:
            continue
        name = normalize_name(name_raw)
        e_type = e.get("entity_type", "Company")

        if e_type == "Company":
            ts = e.get("ts_code", "").strip()
            if ts and looks_like_ts_code(ts):
                entity_id = f"C:{ts}"
            else:
                # Layer 1: alias table (synchronous)
                entity_id, _ = resolve_company_id(name)

                # Layer 2: LLM fallback 需要异步上下文，在此同步版本中跳过
                if entity_id.startswith("CO:") and disambiguation_context:
                    logger.debug("LLM 消歧跳过（同步上下文）: %s", name)
        else:
            entity_id = entity_id_from_name(name, e_type)

        lookup[name] = entity_id
        lookup[name.lower()] = entity_id

    return lookup


async def build_name_to_id_map_async(
    merged_entities: list[dict],
    ts_code: str,
    disambiguation_context: str = "",
) -> dict[str, str]:
    """
    从实体列表构建 name → entity_id 映射（异步版本，支持 LLM 消歧）。

    Company 实体优先用 ts_code 格式，否则用 hash。
    名称统一归一化，消除同一实体不同写法的重复节点。
    """
    lookup: dict[str, str] = {}
    for e in merged_entities:
        name_raw = e.get("entity_name", "").strip()
        if not name_raw:
            continue
        name = normalize_name(name_raw)
        e_type = e.get("entity_type", "Company")

        if e_type == "Company":
            ts = e.get("ts_code", "").strip()
            if ts and looks_like_ts_code(ts):
                entity_id = f"C:{ts}"
            else:
                # Layer 1: alias table (synchronous)
                entity_id, _ = resolve_company_id(name)

                # Layer 2: LLM fallback for CO:-prefixed entity_ids
                if entity_id.startswith("CO:") and disambiguation_context:
                    try:
                        decision, resolved_id = await disambiguate_with_llm(name, disambiguation_context)
                        if resolved_id:
                            entity_id = resolved_id
                    except Exception as disambig_err:
                        logger.debug("LLM 消歧跳过 [%s]: %s", name, disambig_err)
        else:
            entity_id = entity_id_from_name(name, e_type)

        lookup[name] = entity_id
        lookup[name.lower()] = entity_id

    return lookup
