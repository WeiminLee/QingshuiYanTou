"""
KG 抽取引擎 — V2 Schema（2026-04-14）

架构：
  旧接口（extract_text / extract_document）→ RAGExtractor → Neo4j

核心改进：
  1. 底层委托 RAGExtractor（RAGFlow General 模式）
  2. 修复 entity_id 格式不一致（Industry → IND:{hash}）
  3. 状态机校验（来自独立 state_machine.py）
  4. 信号持久化至 Company 节点属性（persist_signals_to_company_props）

entity_id 统一规则：
  Company（上市） : C:{ts_code}           例：C:600519.SH
  Company（非上市）: CO:{md5[:12]}         例：CO:ABC123DEF456
  Product         : P:{md5[:16]}           例：P:ABCD1234EFGH5678
  Industry（THS）  : I:{ths_code}            例：I:885806.TI（THS格式）
  Industry（抽取）  : IND:{md5[:12]}         例：IND:ABC123DEF456
  Metric          : M:{ts_code}:{hash}     例：M:600519.SH:gm
  Event           : E:{ts_code}:{date}:{hash16}  例：E:300308.SZ:20260411:ABCD1234

子模块：
  - knowledge.confidence: 置信度体系
  - knowledge.state_writer: 状态写入 Neo4j
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text as sql_text

from app.core.database import engine
from app.core.file_security import PathTraversalError, validate_file_path
from app.knowledge.entity_service import (
    generate_entity_id_v4,
    upsert_entity,
    upsert_company,
)
from app.knowledge.relation_service import (
    upsert_relates_v4, infer_relation_type,
)
from app.knowledge.contradiction import (
    detect_contradiction, write_contradiction,
)
from app.knowledge.extraction.rag_extractor import (
    RAGExtractor,
    extract_sync as rag_extract_sync,
    extract_async as rag_extract_async,
)
from app.knowledge.extraction.rag_prompts import (
    RELATES_EXTRACTION_PROMPT,
    METRIC_EXTRACTION_PROMPT,
)
from app.knowledge.extraction.chunker import chunk_by_token
from app.knowledge.extraction.signal_extractor import (
    RuleBasedSignalExtractor,
    persist_signals_to_company_props,
)
from app.knowledge.state_machine import (
    infer_state_from_text,
    extract_state_transitions,
    build_transition_signal,
)
from app.knowledge.vector_client import (
    upsert_entity_vector,
    upsert_relation_vector,
    upsert_chunk_vector,
)

# 从 confidence 模块导入（保持向后兼容）
from app.knowledge.confidence import (
    ConfidenceTier,
    SourceConfig,
    SOURCE_CONFIG,
    _source_confidence,
)

# 从 state_writer 模块导入（保持向后兼容）
from app.knowledge.state_writer import (
    write_state_to_neo4j as _write_state_to_neo4j,
    write_transition_to_neo4j as _write_transition_to_neo4j,
)

logger = logging.getLogger(__name__)

# Phase 31 D-C3 — inline from deleted document_service.py
# SAFE_BASE_DIR: 项目根目录（backend/..），用于 validate_file_path 的安全基准
SAFE_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ANNOUNCEMENT_FALLBACK_SOURCE_TYPES = {"announcement", "annual_report"}
_METRIC_TERMS = (
    "营业收入",
    "归属于上市公司股东的净利润",
    "归母净利润",
    "扣除非经常性损益后的净利润",
    "扣非净利润",
    "净利润",
    "毛利率",
    "基本每股收益",
)


def _entity_id_from_name(
    name: str,
    entity_type: str,
    ts_code: str | None = None,
    period: str | None = None,
) -> str:
    """Generate a Schema V4 entity id from extracted entity fields."""
    return generate_entity_id_v4(
        entity_type=entity_type,
        name=name,
        ts_code=ts_code,
        metric_name=name if entity_type == "Metric" else None,
        period=period,
    )


def _build_name_to_id_map(
    entities: list[dict],
    ts_code: str,
    disambiguation_context: str | None = None,
) -> dict[str, str]:
    """Build lookup for extracted names to deterministic V4 IDs."""
    lookup: dict[str, str] = {}
    for entity in entities:
        name = str(entity.get("entity_name") or "").strip()
        if not name:
            continue
        entity_type = str(entity.get("entity_type") or "Company").strip()
        metric = entity.get("metric") if isinstance(entity.get("metric"), dict) else {}
        period = metric.get("period") if metric else None
        try:
            entity_id = _entity_id_from_name(name, entity_type, ts_code=ts_code, period=period)
        except ValueError:
            if entity_type == "Company":
                entity_id = f"CO:{hashlib.md5(name.encode('utf-8')).hexdigest()[:12]}"
            else:
                entity_id = generate_entity_id_v4("Product", name)
        lookup[name] = entity_id
        lookup[name.lower()] = entity_id
    return lookup


def _validate_metric(entity: dict) -> bool:
    """Schema V4 allows fuzzy metric mentions when a period is present."""
    metric = entity.get("metric") if isinstance(entity.get("metric"), dict) else {}
    if not metric:
        return True
    return bool(metric.get("name") and metric.get("period"))


def _is_noise_entity_name(name: str) -> bool:
    value = (name or "").strip()
    if not value:
        return True
    if value in {"---", "--", "-", "###", "##", "#", "RELATES", "METRIC", "Entity", "Relation"}:
        return True
    if re.fullmatch(r"[\W_]+", value, flags=re.UNICODE):
        return True
    if re.match(r"^#{1,6}\s*", value):
        return True
    if any(marker in value for marker in ("实体列表", "关系列表", "RELATES 关系", "METRIC 指标")):
        return True
    return False


def _filter_extraction_noise(
    entities: list[dict],
    relations: list[dict],
) -> tuple[list[dict], list[dict], dict[str, int]]:
    clean_entities: list[dict] = []
    valid_names: set[str] = set()
    dropped_entities = 0
    for entity in entities:
        name = str(entity.get("entity_name") or "").strip()
        if _is_noise_entity_name(name):
            dropped_entities += 1
            continue
        clean_entities.append(entity)
        valid_names.add(name)
        valid_names.add(name.lower())

    clean_relations: list[dict] = []
    dropped_relations = 0
    for rel in relations:
        src = str(rel.get("src_id") or "").strip()
        tgt = str(rel.get("tgt_id") or "").strip()
        if _is_noise_entity_name(src) or _is_noise_entity_name(tgt):
            dropped_relations += 1
            continue
        if src not in valid_names and src.lower() not in valid_names:
            dropped_relations += 1
            continue
        if tgt not in valid_names and tgt.lower() not in valid_names:
            dropped_relations += 1
            continue
        clean_relations.append(rel)

    stats = {"entities_dropped": dropped_entities, "relations_dropped": dropped_relations}
    if dropped_entities or dropped_relations:
        logger.info("抽取噪声过滤: %s", stats)
    return clean_entities, clean_relations, stats


async def _lookup_company_name(ts_code: str, source_name: str = "") -> str:
    if not ts_code or ts_code == "UNKNOWN":
        return ts_code
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sql_text(
                        """
                        SELECT name
                        FROM announcements
                        WHERE ts_code = :ts_code
                          AND name IS NOT NULL
                          AND name <> ''
                          AND (:source_name = '' OR title = :source_name OR :source_name LIKE title || '%%')
                        ORDER BY ann_date DESC NULLS LAST
                        LIMIT 1
                        """
                    ),
                    {"ts_code": ts_code, "source_name": source_name},
                )
            ).first()
            if not row:
                row = (
                    await conn.execute(
                        sql_text("SELECT name FROM stocks WHERE ts_code = :ts_code LIMIT 1"),
                        {"ts_code": ts_code},
                    )
                ).first()
        if row and row[0]:
            return str(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("公司名称查询失败 [%s]: %s", ts_code, exc)
    return ts_code


def _infer_period_from_announcement(text: str, source_name: str) -> tuple[str, str]:
    sample = f"{source_name}\n{text[:1500]}"
    year_match = re.search(r"(20\d{2})\s*年", sample)
    year = year_match.group(1) if year_match else str(date.today().year)
    if "第一季度" in sample or "一季度" in sample:
        return f"{year}Q1", "quarterly"
    if "第三季度" in sample or "三季度" in sample:
        return f"{year}Q3", "quarterly"
    if "半年度" in sample or "半年报" in sample:
        return f"{year}H1", "half-year"
    if "预告" in sample or "预计" in sample:
        return f"{year}E", "forecast"
    return f"{year}A", "actual"


def _metric_unit_near(text: str, term: str) -> str | None:
    idx = text.find(term)
    if idx < 0:
        return None
    window = text[idx : idx + 180]
    for unit in ("亿元", "万元", "元", "%", "GWh", "MWh", "吨", "万股"):
        if unit in window:
            return unit
    return None


async def _apply_announcement_fallback(
    merged_entities: list[dict],
    merged_relations: list[dict],
    *,
    text: str,
    ts_code: str,
    source_name: str,
    source_type: str,
) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """Add deterministic official-disclosure facts when LLM extraction misses basics."""
    if source_type not in ANNOUNCEMENT_FALLBACK_SOURCE_TYPES:
        return merged_entities, merged_relations, {"applied": False}

    added_entities = 0
    added_relations = 0
    existing = {(e.get("entity_name"), e.get("entity_type")) for e in merged_entities}
    company_name = await _lookup_company_name(ts_code, source_name)
    if company_name and (company_name, "Company") not in existing:
        merged_entities.append({
            "entity_name": company_name,
            "entity_type": "Company",
            "description": f"{source_name}公告主体",
            "descriptions": [f"{source_name}公告主体"],
            "source_ids": [source_name],
            "instance_count": 1,
        })
        existing.add((company_name, "Company"))
        added_entities += 1

    period, period_type = _infer_period_from_announcement(text, source_name)
    relation_keys = {(r.get("src_id"), r.get("tgt_id"), r.get("description")) for r in merged_relations}
    for term in _METRIC_TERMS:
        if term not in text:
            continue
        unit = _metric_unit_near(text, term)
        metric = {
            "name": term,
            "value": None,
            "unit": unit,
            "period": period,
            "period_type": period_type,
            "sentiment": "neutral",
        }
        if (term, "Metric") not in existing:
            merged_entities.append({
                "entity_name": term,
                "entity_type": "Metric",
                "description": f"{source_name}披露{period}{term}",
                "descriptions": [f"{source_name}披露{period}{term}"],
                "metric": metric,
                "source_ids": [source_name],
                "instance_count": 1,
            })
            existing.add((term, "Metric"))
            added_entities += 1
        desc = f"{source_name}披露{period}{term}"
        rel_key = (company_name, term, desc)
        if company_name and rel_key not in relation_keys:
            merged_relations.append({
                "src_id": company_name,
                "tgt_id": term,
                "description": desc,
                "descriptions": [desc],
                "keywords": "公告披露",
                "direction": "neutral",
                "weight": 1.0,
                "source_ids": [source_name],
                "instance_count": 1,
            })
            relation_keys.add(rel_key)
            added_relations += 1

    metadata = {
        "applied": bool(added_entities or added_relations),
        "entities_added": added_entities,
        "relations_added": added_relations,
        "period": period,
        "company_name": company_name,
    }
    if metadata["applied"]:
        logger.info("公告兜底补齐: %s", metadata)
    return merged_entities, merged_relations, metadata


def _extract_text_from_file(file_path: Path, file_ext: str) -> str:
    """从文件提取纯文本（Phase 31 D-C3：原 document_service.extract_text_from_file）。

    支持 .txt / .pdf。路径必须在 SAFE_BASE_DIR 内，否则返回空串。
    """
    try:
        file_path = validate_file_path(file_path, SAFE_BASE_DIR)
    except (ValueError, PathTraversalError) as e:
        logger.error("路径安全验证失败 %s: %s", file_path, e)
        return ""
    try:
        if file_ext == ".txt":
            return file_path.read_text(encoding="utf-8", errors="replace")
        if file_ext == ".pdf":
            try:
                from app.knowledge.ingestion.pdf_parser import extract_text_from_pdf
                return extract_text_from_pdf(str(file_path))
            except Exception as pdf_err:
                logger.warning("PDF 解析失败: %s", pdf_err)
                return ""
        logger.warning("不支持的文件格式: %s", file_ext)
        return ""
    except Exception as e:
        logger.error("文本提取失败 %s: %s", file_path, e)
        return ""

# ── Company 别名解析 ─────────────────────────────────────────────────────────
# 委派给 StockNameResolver（PostgreSQL 主源 + supplemental_aliases.json 补充）
# 历史的 _ALIAS_MAP / _CO_CACHE / _load_aliases() 已移除（2026-05-09 P1 重构）


# ── 主抽取函数（保留旧接口，内部委托 RAGExtractor）───────────────────────

def extract_text(
    text: str,
    ts_code: str,
    source_name: str,
    source_type: str = "uploaded_doc",
    article_ref: str = "",
    chunk_size: int = 3000,
) -> dict[str, Any]:
    """
    从文本中抽取实体和关系，注入 Neo4j。

    Args:
        chunk_size: 旧参数（已废弃，统一用 4096 tokens）

    Returns:
            "entities_created": int,
            "entities_updated": int,
            "relations_created": int,
            "relations_updated": int,
            "entities": [entity_id, ...],
            "relations": [{"from": ..., "to": ..., "relation": ...}],
            "chunks_processed": int,
        }
    """
    # ── 构建 source_file（文件名@今日日期）───────────────────────────
    from datetime import date as _date
    source_file = f"{article_ref}@{_date.today().isoformat()}" if article_ref else None

    # 调用 RAGExtractor（同步），只分块一次，chunks 同时用于抽取和向量写入
    chunks = chunk_by_token(text, max_tokens=1024, overlap_tokens=0)
    if not chunks:
        logger.warning("文本为空，跳过抽取: %s", source_name)
        return {
            "entities_created": 0, "entities_updated": 0,
            "relations_created": 0, "relations_updated": 0,
            "entities": [], "relations": [], "chunks_processed": 0,
        }

    try:
        # B8 fix: 传递 source_type 参数
        merged_entities, merged_relations = rag_extract_sync(text, chunks=chunks, source_file=source_file, source_type=source_type)
    except Exception as e:
        logger.warning("RAGExtractor 调用失败 [%s]: %s", source_name, e)
        return {
            "entities_created": 0, "entities_updated": 0,
            "relations_created": 0, "relations_updated": 0,
            "entities": [], "relations": [], "chunks_processed": len(chunks),
            "error": str(e),
        }

    logger.info(
        "RAGExtractor 完成: %s → 实体=%d, 关系=%d",
        source_name, len(merged_entities), len(merged_relations),
    )

    # ── 文档 Chunk 向量写入 ───────────────────────────────────────
    # BUG-12 修复：添加失败计数器，避免静默失败
    chunks_written = 0
    chunks_failed = 0
    for ch in chunks:
        try:
            chunk_text = ch.content if hasattr(ch, "content") else ch.get("content", "")
            if not chunk_text:
                continue
            chunk_id_val = ch.chunk_id if hasattr(ch, "chunk_id") else ch.get("chunk_id", 0)
            upsert_chunk_vector(
                chunk_id=f"{ts_code}:{source_name}:{chunk_id_val}",
                content=chunk_text,
                heading=getattr(ch, "heading", "") or "",
                source=source_name,
                ts_code=ts_code,
            )
            chunks_written += 1
        except Exception as ch_ex:
            chunks_failed += 1
            logger.warning(
                "Chunk 向量写入失败 [%s:%d]: %s (已成功: %d, 已失败: %d)",
                source_name, getattr(ch, "chunk_id", 0), ch_ex, chunks_written, chunks_failed
            )

    # 建立 name → entity_id 查找表
    lookup = _build_name_to_id_map(merged_entities, ts_code)

    # 注入 Neo4j
    entities_created = entities_updated = 0
    relations_created = relations_updated = 0
    entity_ids: list[str] = []
    written_rels: list[dict] = []

    today = date.today()
    conf, tier = _source_confidence(source_type)

    for e in merged_entities:
        name = e.get("entity_name", "").strip()
        e_type = e.get("entity_type", "Company")
        description = e.get("description", "")
        metric = e.get("metric") if isinstance(e.get("metric"), dict) else {}
        props = {
            "original_name": name,
            "description": description,
            "confidence_tier": tier.name,
            "source_type": source_type,
        }
        if metric:
            props.update({
                "metric_value": metric.get("value"),
                "metric_unit": metric.get("unit"),
                "period": metric.get("period"),
                "period_type": metric.get("period_type"),
                "sentiment": metric.get("sentiment"),
            })

        entity_id = lookup.get(name) or lookup.get(name.lower())
        if not entity_id:
            entity_id = _entity_id_from_name(name, e_type)

        try:
            if e_type == "Company":
                if entity_id.startswith("C:"):
                    _, is_new = upsert_company(
                        ts_code=entity_id[2:],
                        name=name,
                        source_type=source_type,
                        source_name=source_name,
                        properties=props,
                    )
                else:
                    _, is_new = upsert_entity(
                        entity_id=entity_id,
                        entity_type="Company",
                        name=name,
                        properties=props,
                        source_type=source_type,
                        source_name=source_name,
                        confidence=conf,
                    )
            else:
                _, is_new = upsert_entity(
                    entity_id=entity_id,
                    entity_type=e_type,
                    name=name,
                    ts_code=ts_code if e_type in {"Metric", "Project"} else None,
                    properties=props,
                    source_type=source_type,
                    source_name=source_name,
                    confidence=conf,
                )

            if is_new:
                entities_created += 1
            else:
                entities_updated += 1
            entity_ids.append(entity_id)

            # ── 向量库写入（实体描述）─────────────────────────────
            try:
                upsert_entity_vector(
                    entity_id=entity_id,
                    entity_name=name,
                    description=description,
                    entity_type=e_type,
                    ts_code=ts_code,
                )
            except Exception as vec_ex:
                logger.debug("实体向量写入跳过 [%s]: %s", entity_id, vec_ex)

        except Exception as ex:
            logger.warning("实体入库失败 [%s %s]: %s", e_type, name, ex)

    # 关系入库（结构化类型 + direction）
    for r in merged_relations:
        src_name = r.get("src_id", "").strip()
        tgt_name = r.get("tgt_id", "").strip()
        rel_desc = r.get("description", "").strip()
        direction = r.get("direction", "neutral")
        has_conflict = r.get("has_direction_conflict", False)

        src_eid = lookup.get(src_name) or lookup.get(src_name.lower())
        tgt_eid = lookup.get(tgt_name) or lookup.get(tgt_name.lower())

        if not src_eid or not tgt_eid:
            logger.debug("关系跳过（节点不存在）: %s → %s", src_name, tgt_name)
            continue

        raw_weight = float(r.get("weight", 5.0))
        v4_weight = min(1.0, raw_weight / 10.0) if raw_weight > 1.0 else raw_weight

        try:
            _, is_new = upsert_relates_v4(
                from_entity=src_eid,
                to_entity=tgt_eid,
                text=rel_desc,
                weight=v4_weight,
                source_file=source_file,
                source_type=source_type,
                source_name=source_name,
                direction=direction,
                valid_from=today,
            )
            if is_new:
                relations_created += 1
            else:
                relations_updated += 1
            written_rels.append({
                "from": src_eid,
                "to": tgt_eid,
                "type": "RELATES",
                "direction": direction,
                "relation": rel_desc,
            })

            # ── 矛盾检测（多源冲突时写入 CONTRADICTS 边）───────────────
            try:
                contradiction = detect_contradiction(
                    from_entity=src_eid,
                    to_entity=tgt_eid,
                    relationship_type="RELATES",
                    new_properties={
                        "relation_description": rel_desc,
                        "valid_from": str(today),
                        "source_name": source_name,
                    },
                    new_source_name=source_name,
                )
                if contradiction:
                    write_contradiction(src_eid, tgt_eid, contradiction)
                    logger.info(
                        "多源冲突 [%s → %s]: %s (%s)",
                        src_eid, tgt_eid, contradiction.get("type"), source_name,
                    )
            except Exception as contra_err:
                logger.debug("矛盾检测失败: %s", contra_err)

            # ── 向量库写入（关系描述）───────────────────────────
            try:
                upsert_relation_vector(
                    relation_key=f"{src_eid}|{tgt_eid}|{rel_desc[:40]}",
                    from_name=src_name,
                    to_name=tgt_name,
                    description=rel_desc,
                    from_entity=src_eid,
                    to_entity=tgt_eid,
                    ts_code=ts_code,
                )
            except Exception as vec_ex:
                logger.debug("关系向量写入跳过 [%s → %s]: %s", src_eid, tgt_eid, vec_ex)

        except Exception as ex:
            logger.warning("关系入库失败 [%s → %s]: %s", src_eid, tgt_eid, ex)

    # ── 状态机推断 + 跃迁提取 ──────────────────────────────────────────
    current_state = infer_state_from_text(text)
    state_transitions: list[dict] = []
    investment_signal: dict = {}

    if current_state:
        logger.info("文本状态推断: %s → %s", source_name, current_state.value)
        _write_state_to_neo4j(ts_code, current_state, source_name, source_type)

        # 提取状态跃迁并写入 Neo4j
        try:
            raw_transitions = extract_state_transitions(text)
            if raw_transitions:
                for st in raw_transitions:
                    if st.direction == "neutral":
                        continue  # 跳过同态维持
                    _write_transition_to_neo4j(
                        ts_code=ts_code,
                        transition=st,
                        source_name=source_name,
                        source_type=source_type,
                    )
                    state_transitions.append({
                        "from": st.from_state.value,
                        "to": st.to_state.value,
                        "direction": st.direction,
                        "evidence": st.evidence[:100],
                        "confidence": st.confidence,
                        "source_type": st.source_type,
                    })
                investment_signal = build_transition_signal(raw_transitions)
                logger.info(
                    "状态跃迁提取: %s → %d 条跃迁，信号=%s",
                    source_name, len(raw_transitions), investment_signal.get("signal", "none"),
                )
        except Exception as st_ex:
            logger.warning("状态跃迁提取失败 [%s]: %s", source_name, st_ex)

    # ── 信号提取（写入 Company 节点属性，替代 Event 节点）────────────
    company_signals: dict = {}
    try:
        extractor = RuleBasedSignalExtractor()
        # 截断文本防止关键词匹配过长
        sig_text = text[:10000]
        signals_result = extractor.extract_sync(sig_text, source_type, {"ts_code": ts_code})
        company_signals = persist_signals_to_company_props(
            signals_result,
            ts_code=ts_code,
            source_type=source_type,
            source_document_id=article_ref,
        )
    except Exception as sig_ex:
        logger.warning("信号提取失败 [%s]: %s", source_name, sig_ex)

    return {
        "entities_created": entities_created,
        "entities_updated": entities_updated,
        "relations_created": relations_created,
        "relations_updated": relations_updated,
        "entities": entity_ids,
        "relations": written_rels,
        "chunks_processed": len(chunks),
        "chunks_vector_written": chunks_written,
        "company_signals": company_signals,
        "inferred_state": current_state.value if current_state else None,
        "state_transitions": state_transitions,
        "investment_signal": investment_signal,
        "source_type": source_type,
        "confidence_tier": tier.name,
        "confidence_score": conf,
    }


# ── 异步版本（供 asyncio 管道调用，避免嵌套 event loop）───────────────

async def extract_text_async(
    text: str,
    ts_code: str,
    source_name: str,
    source_type: str = "uploaded_doc",
    article_ref: str = "",
    progress_callback: "Callable[[str, float], None] | None" = None,
    file_path: str | None = None,
    chunk_max_tokens: int = 1024,
    max_chunks: int | None = None,
) -> dict[str, Any]:
    """
    extract_text 的异步版本，内部直接调用 RAGExtractor.extract()（避免 asyncio.run 嵌套）。

    修复：只分块一次，chunks 同时用于 LLM 抽取和向量写入，不再二次分块。

    Args:
        progress_callback: 进度回调 (message, percent)，各抽取阶段写入日志
        file_path: 文件路径，用于获取文件创建日期，构建 source_file
    """
    # ── 构建 source_file（文件名@文件创建日期）─────────────────────────
    source_file: str | None = None
    if article_ref and file_path:
        try:
            import os
            from datetime import date as _date
            # 优先 st_ctime（创建时间），fallback st_mtime（修改时间）
            stat = os.stat(file_path)
            file_date = _date.fromtimestamp(stat.st_ctime or stat.st_mtime)
            source_file = f"{article_ref}@{file_date.isoformat()}"
        except Exception as e:
            logger.warning("无法获取文件创建日期，降级为今天: %s — %s", file_path, e)
            source_file = f"{article_ref}@{_date.today().isoformat()}"
    elif article_ref:
        from datetime import date as _date
        source_file = f"{article_ref}@{_date.today().isoformat()}"

    chunks = chunk_by_token(text, max_tokens=chunk_max_tokens, overlap_tokens=0)
    if not chunks:
        logger.warning("文本为空，跳过抽取: %s", source_name)
        return {
            "entities_created": 0, "entities_updated": 0,
            "relations_created": 0, "relations_updated": 0,
            "entities": [], "relations": [], "chunks_processed": 0,
        }
    chunks_total = len(chunks)
    chunk_budget_applied = False
    if max_chunks is not None and max_chunks > 0 and len(chunks) > max_chunks:
        chunks = chunks[:max_chunks]
        chunk_budget_applied = True
        progress_callback and progress_callback(
            f"应用 chunk 预算: {chunks_total} → {len(chunks)}",
            6.0,
        )

    # RAGExtractor 异步抽取（复用同一批 chunks，不再二次分块）
    # 重要参数说明（RAGFlow General 模式参考值）：
    #   max_tokens=512：每个 chunk 约 512 tokens，平衡上下文完整性与实体召回
    #   overlap_tokens=0：抽取无需 overlap，实体去重由合并阶段处理
    progress_callback and progress_callback(f"分块完成，共 {len(chunks)} 个 chunk", 5.0)
    try:
        merged_entities, merged_relations = await rag_extract_async(
            text,
            chunks=chunks,             # 预分块，与向量写入使用同一批 chunks
            max_tokens=1024,          # 2026-04-14 重构：512 → 1024，提升实体召回率
            overlap_tokens=0,         # 无 overlap，抽取场景不需要
            callback=progress_callback,
            source_file=source_file,  # 文件名@日期，descriptions.source 标记
            source_type=source_type,  # 决定使用哪个抽取 prompt
        )
        progress_callback and progress_callback(f"实体合并完成: {len(merged_entities)} 实体", 70.0)
    except Exception as e:
        logger.warning("RAGExtractor 调用失败 [%s]: %s", source_name, e)
        return {
            "entities_created": 0, "entities_updated": 0,
            "relations_created": 0, "relations_updated": 0,
            "entities": [], "relations": [], "chunks_processed": len(chunks),
            "error": str(e),
        }

    logger.info(
        "RAGExtractor 完成: %s → 实体=%d, 关系=%d",
        source_name, len(merged_entities), len(merged_relations),
    )
    merged_entities, merged_relations, fallback_info = await _apply_announcement_fallback(
        merged_entities,
        merged_relations,
        text=text,
        ts_code=ts_code,
        source_name=source_name,
        source_type=source_type,
    )
    merged_entities, merged_relations, noise_filter_info = _filter_extraction_noise(
        merged_entities,
        merged_relations,
    )

    # ── Chunk 向量（复用同一批 chunks，与 LLM 抽取的 chunk_id 完全对齐）──
    # BUG-12 修复：添加失败计数器
    chunks_written = 0
    chunks_failed = 0
    for ch in chunks:
        try:
            chunk_text = ch.content if hasattr(ch, "content") else ch.get("content", "")
            if not chunk_text:
                continue
            chunk_id_val = ch.chunk_id if hasattr(ch, "chunk_id") else ch.get("chunk_id", 0)
            upsert_chunk_vector(
                chunk_id=f"{ts_code}:{source_name}:{chunk_id_val}",
                content=chunk_text,
                heading=getattr(ch, "heading", "") or "",
                source=source_name,
                ts_code=ts_code,
            )
            chunks_written += 1
        except Exception as ch_ex:
            chunks_failed += 1
            logger.warning(
                "Chunk 向量写入失败 [%s:%d]: %s",
                source_name, getattr(ch, "chunk_id", 0), ch_ex
            )

    lookup = _build_name_to_id_map(merged_entities, ts_code, disambiguation_context=text[:500])
    today = date.today()
    conf, tier = _source_confidence(source_type)

    # ── 实体入库 ─────────────────────────────────────────────────
    entities_created = entities_updated = 0
    entity_ids: list[str] = []

    for e in merged_entities:
        name = e.get("entity_name", "").strip()
        e_type = e.get("entity_type", "Company")
        description = e.get("description", "")
        metric = e.get("metric") if isinstance(e.get("metric"), dict) else {}
        props = {
            "original_name": name,
            "description": description,
            "confidence_tier": tier.name,
            "source_type": source_type,
        }
        if metric:
            props.update({
                "metric_value": metric.get("value"),
                "metric_unit": metric.get("unit"),
                "period": metric.get("period"),
                "period_type": metric.get("period_type"),
                "sentiment": metric.get("sentiment"),
            })
        entity_id = lookup.get(name) or lookup.get(name.lower()) or _entity_id_from_name(name, e_type)

        try:
            # ── Metric 量化校验（V2 Schema 强制规则）───────────────
            if e_type == "Metric" and not _validate_metric(e):
                logger.debug("Metric 节点跳过（无数值）: %s", name)
                continue

            if e_type == "Company":
                if entity_id.startswith("C:"):
                    _, is_new = upsert_company(
                        ts_code=entity_id[2:],
                        name=name,
                        source_type=source_type,
                        source_name=source_name,
                        properties=props,
                    )
                else:
                    _, is_new = upsert_entity(
                        entity_id=entity_id,
                        entity_type="Company",
                        name=name,
                        properties=props,
                        source_type=source_type,
                        source_name=source_name,
                        confidence=conf,
                    )
            else:
                _, is_new = upsert_entity(
                    entity_id=entity_id,
                    entity_type=e_type,
                    name=name,
                    ts_code=ts_code if e_type in {"Metric", "Project"} else None,
                    properties=props,
                    source_type=source_type,
                    source_name=source_name,
                    confidence=conf,
                )
            if is_new:
                entities_created += 1
            else:
                entities_updated += 1
            entity_ids.append(entity_id)
            try:
                upsert_entity_vector(
                    entity_id=entity_id,
                    entity_name=name,
                    description=description,
                    entity_type=e_type,
                    ts_code=ts_code,
                )
            except Exception as ve:
                logger.debug("实体向量写入失败 [%s]: %s", entity_id, ve)
        except Exception as ex:
            logger.warning("实体入库失败 [%s %s]: %s", e_type, name, ex)

    # ── 关系入库（V2 Schema：统一 RELATES 类型）─────────────────────────
    # 2026-04-14 重构：
    # - 新抽取的关系写入 upsert_relates()（统一 RELATES 类型，text + weight）
    # - 旧有 typed 关系通过 kg_cleanup_v2.py 脚本迁移，不在此处同时写
    # - source_file 用于 descriptions.source 标记
    relations_created = relations_updated = 0
    written_rels: list[dict] = []

    for r in merged_relations:
        src_name = r.get("src_id", "").strip()
        tgt_name = r.get("tgt_id", "").strip()
        rel_desc = r.get("description", "").strip()
        direction = r.get("direction", "neutral")
        has_conflict = r.get("has_direction_conflict", False)

        src_eid = lookup.get(src_name) or lookup.get(src_name.lower())
        tgt_eid = lookup.get(tgt_name) or lookup.get(tgt_name.lower())
        if not src_eid or not tgt_eid:
            continue

        # 从 weight 字段计算 V2 weight（V1 输出是 1-10，V2 需要 0-1 映射）
        raw_weight = float(r.get("weight", 5.0))
        v2_weight = min(1.0, raw_weight / 10.0) if raw_weight > 1.0 else raw_weight

        try:
            _, is_new = upsert_relates_v4(
                from_entity=src_eid,
                to_entity=tgt_eid,
                text=rel_desc,
                weight=v2_weight,
                source_file=source_file,
                source_type=source_type,
                source_name=source_name,
                direction=direction,
                valid_from=today,
            )
            if is_new:
                relations_created += 1
            else:
                relations_updated += 1
            written_rels.append({
                "from": src_eid, "to": tgt_eid,
                "type": "RELATES", "direction": direction,
                "relation": rel_desc,
            })

            # ── 矛盾检测（多源冲突时写入 CONTRADICTS 边）───────────────
            try:
                contradiction = detect_contradiction(
                    from_entity=src_eid,
                    to_entity=tgt_eid,
                    relationship_type="RELATES",
                    new_properties={
                        "relation_description": rel_desc,
                        "valid_from": str(today),
                        "source_name": source_name,
                    },
                    new_source_name=source_name,
                )
                if contradiction:
                    write_contradiction(src_eid, tgt_eid, contradiction)
                    logger.info(
                        "多源冲突 [%s → %s]: %s (%s)",
                        src_eid, tgt_eid, contradiction.get("type"), source_name,
                    )
            except Exception as contra_err:
                logger.debug("矛盾检测失败: %s", contra_err)

            # ── 向量库写入 ──────────────────────────────────────────
            try:
                upsert_relation_vector(
                    relation_key=f"{src_eid}|{tgt_eid}|{rel_desc[:40]}",
                    from_name=src_name, to_name=tgt_name,
                    description=rel_desc,
                    from_entity=src_eid, to_entity=tgt_eid,
                    ts_code=ts_code,
                )
            except Exception as e:
                logger.warning("关系向量写入失败 [%s → %s]: %s", src_eid, tgt_eid, e)
        except Exception as ex:
            logger.warning("关系入库失败 [%s → %s]: %s", src_eid, tgt_eid, ex)

    # ── 状态机 + 信号 ───────────────────────────────────────────
    current_state = infer_state_from_text(text)
    state_transitions, investment_signal = [], {}

    if current_state:
        _write_state_to_neo4j(ts_code, current_state, source_name, source_type)
        try:
            raw_transitions = extract_state_transitions(text)
            for st in raw_transitions:
                if st.direction == "neutral":
                    continue
                _write_transition_to_neo4j(ts_code, st, source_name, source_type)
                state_transitions.append({
                    "from": st.from_state.value, "to": st.to_state.value,
                    "direction": st.direction,
                    "evidence": st.evidence[:100],
                    "confidence": st.confidence,
                })
            investment_signal = build_transition_signal(raw_transitions)
        except Exception as e:
            logger.warning("状态机转换抽取失败 [%s]: %s", source_name, e)

    company_signals: dict = {}
    try:
        extractor_sig = RuleBasedSignalExtractor()
        signals_result = extractor_sig.extract_sync(text[:10000], source_type, {"ts_code": ts_code})
        company_signals = persist_signals_to_company_props(
            signals_result, ts_code=ts_code,
            source_type=source_type, source_document_id=article_ref,
        )
    except Exception as e:
        logger.warning("信号抽取失败 [%s]: %s", source_name, e)

    return {
        "entities_created": entities_created,
        "entities_updated": entities_updated,
        "relations_created": relations_created,
        "relations_updated": relations_updated,
        "entities": entity_ids,
        "relations": written_rels,
        "chunks_processed": len(chunks),
        "chunks_total": chunks_total,
        "chunk_budget_applied": chunk_budget_applied,
        "chunks_vector_written": chunks_written,
        "company_signals": company_signals,
        "inferred_state": current_state.value if current_state else None,
        "state_transitions": state_transitions,
        "investment_signal": investment_signal,
        "source_type": source_type,
        "confidence_tier": tier.name,
        "confidence_score": conf,
        "fallback": fallback_info,
        "noise_filter": noise_filter_info,
    }


async def extract_document_async(
    file_path: str,
    ts_code: str,
    source_name: str,
    source_type: str = "uploaded_doc",
) -> dict[str, Any]:
    """从 PDF/TXT/MD 文件抽取实体和关系（异步版，直接调用 extract_text_async 避免嵌套 asyncio.run）。"""
    path = Path(file_path)

    # 路径安全验证（SAFE_BASE_DIR 在模块顶层已定义）
    try:
        path = validate_file_path(path, SAFE_BASE_DIR)
    except (ValueError, PathTraversalError) as e:
        raise ValueError(f"路径安全验证失败: {e}") from e

    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    ext = path.suffix.lower()
    if ext not in (".pdf", ".txt", ".md"):
        raise ValueError(f"不支持的文件格式: {ext}，仅支持 PDF/TXT/MD")

    logger.info("开始抽取文档: %s", file_path)

    # MD 文件直接读文本内容
    if ext == ".md":
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        text = _extract_text_from_file(path, ext)

    if not text.strip():
        raise ValueError(f"文本提取为空: {file_path}")

    logger.info("文本提取完成，字数=%d: %s", len(text), file_path)
    return await extract_text_async(
        text=text,
        ts_code=ts_code,
        source_name=source_name,
        source_type=source_type,
        article_ref=path.name,
        file_path=str(path),
    )


async def kg_extraction_task(
    cninfo_id: str,
    file_path: str,
    ts_code: str,
    title: str,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Background task for PDF post-download KG extraction."""
    from app.core.mongodb import get_mongo_db
    from app.knowledge.file_indexer import FileIndexer

    db = get_mongo_db()
    indexer = FileIndexer(db)
    await indexer.ensure_indexes()

    if not Path(file_path).exists():
        error = f"file no longer exists: {file_path}"
        await indexer.mark_failed(file_path, error, max_retries=max_retries)
        return {"status": "failed", "error": error, "entities": 0, "relations": 0}

    await indexer.mark_extracting(file_path)
    try:
        from app.data_pipeline.announcement_filter import classify_title

        doc_type, _ = classify_title(title or Path(file_path).name)
        source_type = "annual_report" if doc_type == "annual_report" else "announcement"
        await indexer.mark_extracting(file_path, source_type=source_type, doc_type=doc_type)
        result = await extract_document_async(
            file_path=file_path,
            ts_code=ts_code,
            source_name=title or cninfo_id,
            source_type=source_type,
        )
        entities_count = int(result.get("entities_created", 0) or 0) + int(result.get("entities_updated", 0) or 0)
        relations_count = int(result.get("relations_created", 0) or 0) + int(result.get("relations_updated", 0) or 0)
        await indexer.mark_done(file_path, entities_count, relations_count, source_type=source_type, doc_type=doc_type)
        logger.info(
            "公告 PDF KG 抽取完成 [%s]: entities=%d relations=%d",
            cninfo_id, entities_count, relations_count,
        )
        return {
            "status": "done",
            "entities": entities_count,
            "relations": relations_count,
            **result,
        }
    except Exception as exc:  # noqa: BLE001
        await indexer.mark_failed(file_path, str(exc), max_retries=max_retries)
        logger.warning("公告 PDF KG 抽取失败 [%s]: %s", cninfo_id, exc)
        return {"status": "failed", "error": str(exc), "entities": 0, "relations": 0}


def extract_document(
    file_path: str,
    ts_code: str,
    source_name: str,
    source_type: str = "uploaded_doc",
) -> dict[str, Any]:
    """从 PDF/TXT/MD 文件抽取实体和关系（同步入口）。

    B3 fix: 如果在已有事件循环的上下文中调用，抛出明确错误而非崩溃。
    从 async context 调用时应使用 extract_document_async 或 asyncio.to_thread。
    """
    try:
        loop = asyncio.get_running_loop()
        raise RuntimeError(
            "extract_document 是同步函数，不应在 async 上下文中直接调用。"
            "请使用 extract_document_async 或 asyncio.to_thread(extract_document, ...)"
        )
    except RuntimeError as e:
        if "async 上下文中" in str(e):
            raise
        # 无运行中的事件循环，正常执行
        return asyncio.run(extract_document_async(file_path, ts_code, source_name, source_type))
