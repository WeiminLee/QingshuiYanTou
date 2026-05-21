"""IRM Q&A knowledge extraction for Schema V4."""
from __future__ import annotations

import logging
import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from app.core.mongodb import get_mongo_db
from app.knowledge.entity_service import generate_entity_id_v4, upsert_entity
from app.knowledge.evidence_builders import build_irm_evidence
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.extraction.rag_extractor import extract_async as rag_extract_async
from app.knowledge.relation_service import upsert_relates_v4
from app.knowledge.vector_client import (
    COLLECTION_QA,
    VectorRecord,
    get_embedding_model,
    get_vector_client,
    upsert_entity_vector,
    upsert_relation_vector,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[..., Awaitable[None]]
IRM_KG_INDEX_COLLECTION = "irm_kg_index"
IRM_KG_SCHEMA_VERSION = "v4"
IRM_KG_PARSER_VERSION = "v4"
_IRM_KG_INDEXES_READY = False


async def _emit(progress_callback: ProgressCallback | None, stage: str, message: str, **kwargs: Any) -> None:
    if progress_callback is None:
        return
    try:
        await progress_callback(stage=stage, message=message, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("IRM progress callback failed [%s]: %s", stage, exc)


def _entity_id(name: str, entity_type: str, ts_code: str) -> str:
    return generate_entity_id_v4(
        entity_type=entity_type,
        name=name,
        ts_code=ts_code if entity_type in {"Company", "Metric", "Project"} else None,
        metric_name=name if entity_type == "Metric" else None,
        period="IRM" if entity_type == "Metric" else None,
    )


def _irm_record_key(rec: dict[str, Any]) -> str:
    cninfo_id = str(rec.get("cninfo_id") or "").strip()
    if cninfo_id:
        return cninfo_id
    ts_code = str(rec.get("ts_code") or "").strip()
    content_hash = _irm_content_hash(rec)
    return f"{ts_code}:{content_hash[:20]}" if ts_code else content_hash[:24]


def _irm_content_hash(rec: dict[str, Any]) -> str:
    payload = "\n".join(
        [
            str(rec.get("ts_code") or ""),
            str(rec.get("company_name") or rec.get("name") or ""),
            str(rec.get("question") or rec.get("title") or ""),
            str(rec.get("answer") or rec.get("type") or ""),
            str(rec.get("ann_date") or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _irm_checkpoint_col():
    global _IRM_KG_INDEXES_READY
    db = get_mongo_db()
    col = db[IRM_KG_INDEX_COLLECTION]
    if not _IRM_KG_INDEXES_READY:
        await col.create_index("record_key", unique=True)
        await col.create_index("cninfo_id")
        await col.create_index("ts_code")
        await col.create_index("status")
        await col.create_index("updated_at")
        _IRM_KG_INDEXES_READY = True
    return col


async def _get_done_checkpoint(record_key: str, content_hash: str) -> dict[str, Any] | None:
    col = await _irm_checkpoint_col()
    doc = await col.find_one(
        {
            "record_key": record_key,
            "content_hash": content_hash,
            "status": "done",
            "schema_version": IRM_KG_SCHEMA_VERSION,
            "parser_version": IRM_KG_PARSER_VERSION,
        },
        {"_id": 0},
    )
    return dict(doc) if doc else None


async def _mark_irm_running(rec: dict[str, Any], record_key: str, content_hash: str) -> None:
    col = await _irm_checkpoint_col()
    now = datetime.utcnow()
    await col.update_one(
        {"record_key": record_key},
        {
            "$set": {
                "cninfo_id": str(rec.get("cninfo_id") or ""),
                "ts_code": str(rec.get("ts_code") or ""),
                "company_name": str(rec.get("company_name") or rec.get("name") or ""),
                "question": str(rec.get("question") or rec.get("title") or "")[:500],
                "content_hash": content_hash,
                "status": "running",
                "schema_version": IRM_KG_SCHEMA_VERSION,
                "parser_version": IRM_KG_PARSER_VERSION,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now, "retry_count": 0},
        },
        upsert=True,
    )


async def _mark_irm_done(record_key: str, result: dict[str, Any]) -> None:
    col = await _irm_checkpoint_col()
    await col.update_one(
        {"record_key": record_key},
        {
            "$set": {
                "status": "done",
                "result": result,
                "entities_count": int(result.get("entities_created", 0) or 0) + int(result.get("entities_updated", 0) or 0),
                "relations_count": int(result.get("relations_created", 0) or 0) + int(result.get("relations_updated", 0) or 0),
                "qa_vector_ok": bool(result.get("qa_vector_ok")),
                "entity_vectors_ok": int(result.get("entity_vectors_ok", 0) or 0),
                "relation_vectors_ok": int(result.get("relation_vectors_ok", 0) or 0),
                "error": None,
                "finished_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        },
    )


async def _mark_irm_failed(record_key: str, error: str) -> None:
    col = await _irm_checkpoint_col()
    await col.update_one(
        {"record_key": record_key},
        {
            "$set": {
                "status": "failed",
                "error": error[:1000],
                "updated_at": datetime.utcnow(),
            },
            "$inc": {"retry_count": 1},
        },
    )


async def upsert_irm_company(ts_code: str, name: str) -> tuple[dict, bool]:
    return upsert_entity(
        entity_id=generate_entity_id_v4("Company", name, ts_code=ts_code),
        entity_type="Company",
        name=name,
        ts_code=ts_code,
        source_type="irm",
        source_name="互动易",
        parser_version="v4",
    )


async def upsert_irm_product(name: str, company_id: str) -> tuple[dict, bool]:
    node, is_new = upsert_entity(
        entity_id=generate_entity_id_v4("Product", name),
        entity_type="Product",
        name=name,
        source_type="irm",
        source_name="互动易",
        parser_version="v4",
    )
    upsert_relates_v4(company_id, node["entity_id"], f"互动易提及公司与产品 {name} 相关", source_type="irm", source_name="互动易")
    return node, is_new


async def upsert_irm_application(name: str) -> tuple[dict, bool]:
    return upsert_entity(generate_entity_id_v4("Application", name), "Application", name, source_type="irm", source_name="互动易", parser_version="v4")


async def upsert_irm_technology(name: str) -> tuple[dict, bool]:
    return upsert_entity(generate_entity_id_v4("Technology", name), "Technology", name, source_type="irm", source_name="互动易", parser_version="v4")


async def upsert_irm_metric(name: str, value: Any = None, period: str = "IRM") -> tuple[dict, bool]:
    props = {"value": value, "period": period}
    return upsert_entity(
        generate_entity_id_v4("Metric", name, ts_code="IRM", metric_name=name, period=period),
        "Metric",
        name,
        ts_code="IRM",
        properties=props,
        source_type="irm",
        source_name="互动易",
        parser_version="v4",
    )


async def create_irm_evidence_jobs(
    records: list[dict[str, Any]],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, int]:
    """Create Evidence-first jobs for IRM records without LLM extraction."""
    service = EvidenceService()
    totals = {"records": len(records), "evidence": 0, "jobs": 0, "fail": 0, "skipped": 0}
    for rec in records:
        item_id = str(rec.get("cninfo_id") or rec.get("ts_code") or "")[:100]
        title = str(rec.get("question") or rec.get("title") or "")[:200]
        try:
            evidence_input = build_irm_evidence(rec)
            saved = await service.upsert_evidence(evidence_input, chunk_index=0)
            jobs = await service.enqueue_default_jobs(saved["evidence_id"])
            totals["evidence"] += 1
            totals["jobs"] += len(jobs)
            await _emit(
                progress_callback,
                "irm_evidence_created",
                "互动易 Evidence 已创建",
                item_id=item_id or None,
                item_title=title,
                metadata={"evidence_id": saved["evidence_id"], "jobs": len(jobs)},
            )
        except Exception as exc:  # noqa: BLE001
            totals["fail"] += 1
            logger.warning("IRM Evidence creation failed [%s]: %s", item_id, exc)
            await _emit(
                progress_callback,
                "irm_evidence_failed",
                "互动易 Evidence 创建失败",
                item_id=item_id or None,
                item_title=title,
                error=str(exc),
            )
    return totals


async def extract_irm_qa(
    question: str,
    answer: str,
    ts_code: str,
    company_name: str,
    cninfo_id: str = "",
    ann_date: Any = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Extract one IRM Q&A into Schema V4 entities and RELATES edges."""
    text = f"问题：{question}\n回答：{answer}"
    await _emit(
        progress_callback,
        "record_start",
        "互动易问答知识抽取开始",
        item_id=cninfo_id or None,
        item_title=question[:200],
        metadata={"ts_code": ts_code, "ann_date": str(ann_date or "")},
    )
    company_node, _ = await upsert_irm_company(ts_code, company_name or ts_code)
    company_id = company_node["entity_id"]
    source_name = f"互动易:{cninfo_id}" if cninfo_id else "互动易"

    await _emit(
        progress_callback,
        "qa_vector_start",
        "互动易问答向量写入开始",
        item_id=cninfo_id or None,
        item_title=question[:200],
    )
    qa_vector_ok = _upsert_qa_vector(
        qa_id=cninfo_id or f"{ts_code}:{question[:80]}",
        question=question,
        answer=answer,
        ts_code=ts_code,
        company_name=company_name,
        ann_date=str(ann_date or ""),
    )
    await _emit(
        progress_callback,
        "qa_vector_done",
        "互动易问答向量写入完成" if qa_vector_ok else "互动易问答向量写入失败",
        item_id=cninfo_id or None,
        item_title=question[:200],
        metadata={"ok": qa_vector_ok},
    )

    await _emit(
        progress_callback,
        "llm_extract_start",
        "互动易问答实体关系抽取开始",
        item_id=cninfo_id or None,
        item_title=question[:200],
    )
    entities, relations = await rag_extract_async(
        text,
        source_type="irm",
        source_file=f"irm:{ts_code}:{cninfo_id}" if cninfo_id else f"irm:{ts_code}",
    )
    await _emit(
        progress_callback,
        "llm_extract_done",
        "互动易问答实体关系抽取完成",
        item_id=cninfo_id or None,
        item_title=question[:200],
        metadata={"entities_extracted": len(entities), "relations_extracted": len(relations)},
    )

    entity_ids: dict[str, str] = {company_name: company_id, ts_code: company_id}
    created = updated = 0
    entity_vector_ok = entity_vector_fail = 0
    mention_relations = mention_relation_vectors_ok = mention_relation_vectors_fail = 0
    for entity in entities:
        name = str(entity.get("entity_name") or "").strip()
        entity_type = str(entity.get("entity_type") or "").strip()
        if not name or entity_type not in {"Company", "Product", "Application", "Technology", "Metric", "Category", "Project"}:
            continue
        try:
            eid = _entity_id(name, entity_type, ts_code)
            node, is_new = upsert_entity(
                entity_id=eid,
                entity_type=entity_type,
                name=name,
                ts_code=ts_code if entity_type in {"Company", "Metric", "Project"} else None,
                properties={"description": entity.get("description", ""), "source_text": text[:500]},
                source_type="irm",
                source_name="互动易",
                parser_version="v4",
            )
            entity_ids[name] = node["entity_id"]
            created += int(is_new)
            updated += int(not is_new)
            if upsert_entity_vector(
                entity_id=node["entity_id"],
                entity_name=name,
                description=entity.get("description", ""),
                entity_type=entity_type,
                ts_code=ts_code,
            ):
                entity_vector_ok += 1
            else:
                entity_vector_fail += 1
            if entity_type != "Company":
                text_desc = f"互动易问答提及 {name}"
                upsert_relates_v4(company_id, node["entity_id"], text_desc, source_type="irm", source_name=source_name)
                mention_relations += 1
                if upsert_relation_vector(
                    relation_key=f"{source_name}|{company_id}|{node['entity_id']}|mention",
                    from_name=company_name or ts_code,
                    to_name=name,
                    description=text_desc,
                    from_entity=company_id,
                    to_entity=node["entity_id"],
                    ts_code=ts_code,
                ):
                    mention_relation_vectors_ok += 1
                else:
                    mention_relation_vectors_fail += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("IRM entity upsert failed [%s/%s]: %s", entity_type, name, exc)

    await _emit(
        progress_callback,
        "entity_upsert_done",
        "互动易实体与实体向量入库完成",
        item_id=cninfo_id or None,
        item_title=question[:200],
        metadata={
            "entities_created": created,
            "entities_updated": updated,
            "entity_vectors_ok": entity_vector_ok,
            "entity_vectors_fail": entity_vector_fail,
            "mention_relations": mention_relations,
            "mention_relation_vectors_ok": mention_relation_vectors_ok,
            "mention_relation_vectors_fail": mention_relation_vectors_fail,
        },
    )

    rel_created = rel_updated = 0
    relation_vector_ok = relation_vector_fail = 0
    for rel in relations:
        src = entity_ids.get(str(rel.get("src_id") or "").strip())
        tgt = entity_ids.get(str(rel.get("tgt_id") or "").strip())
        if not src or not tgt:
            continue
        _, is_new = upsert_relates_v4(
            src,
            tgt,
            str(rel.get("description") or ""),
            weight=float(rel.get("weight") or 0.7),
            source_type="irm",
            source_name=source_name,
        )
        if upsert_relation_vector(
            relation_key=f"{source_name}|{src}|{tgt}|{str(rel.get('description') or '')[:40]}",
            from_name=str(rel.get("src_id") or ""),
            to_name=str(rel.get("tgt_id") or ""),
            description=str(rel.get("description") or ""),
            from_entity=src,
            to_entity=tgt,
            ts_code=ts_code,
        ):
            relation_vector_ok += 1
        else:
            relation_vector_fail += 1
        rel_created += int(is_new)
        rel_updated += int(not is_new)

    await _emit(
        progress_callback,
        "relation_upsert_done",
        "互动易关系与关系向量入库完成",
        item_id=cninfo_id or None,
        item_title=question[:200],
        metadata={
            "relations_created": rel_created,
            "relations_updated": rel_updated,
            "relation_vectors_ok": relation_vector_ok,
            "relation_vectors_fail": relation_vector_fail,
        },
    )

    return {
        "entities_created": created,
        "entities_updated": updated,
        "relations_created": rel_created,
        "relations_updated": rel_updated,
        "qa_vector_ok": qa_vector_ok,
        "entity_vectors_ok": entity_vector_ok,
        "entity_vectors_fail": entity_vector_fail,
        "relation_vectors_ok": relation_vector_ok + mention_relation_vectors_ok,
        "relation_vectors_fail": relation_vector_fail + mention_relation_vectors_fail,
        "mention_relations": mention_relations,
        "company_id": company_id,
    }


def _upsert_qa_vector(
    qa_id: str,
    question: str,
    answer: str,
    ts_code: str,
    company_name: str,
    ann_date: str = "",
) -> bool:
    try:
        embedder = get_embedding_model()
        client = get_vector_client()
        content = f"问题：{question}\n回答：{answer}"
        vec = embedder.embed(content)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(qa_id)))
        client.upsert(
            COLLECTION_QA,
            [
                VectorRecord(
                    id=point_id,
                    vector=vec,
                    payload={
                        "qa_id": qa_id,
                        "question": question,
                        "answer": answer,
                        "source": "互动易",
                        "ts_code": ts_code,
                        "company_name": company_name,
                        "ann_date": ann_date,
                    },
                )
            ],
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("IRM QA vector upsert failed [%s]: %s", qa_id, exc)
        return False


async def extract_irm_batch(
    records: list[dict],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, int]:
    totals = {
        "records": 0,
        "entities": 0,
        "relations": 0,
        "fail": 0,
        "skipped": 0,
        "qa_vectors": 0,
        "entity_vectors": 0,
        "relation_vectors": 0,
    }
    total_records = len(records)
    for idx, rec in enumerate(records, start=1):
        cninfo_id = str(rec.get("cninfo_id") or "")
        question = str(rec.get("question") or rec.get("title") or "")
        record_key = _irm_record_key(rec)
        content_hash = _irm_content_hash(rec)
        try:
            await _emit(
                progress_callback,
                "record_progress",
                "互动易问答处理进展",
                total_items=total_records,
                processed_items=idx - 1,
                success_count=totals["records"],
                skipped_count=totals["skipped"],
                fail_count=totals["fail"],
                item_id=cninfo_id or None,
                item_title=question[:200],
            )
            checkpoint = await _get_done_checkpoint(record_key, content_hash)
            if checkpoint:
                totals["skipped"] += 1
                cached_result = checkpoint.get("result") or {}
                await _emit(
                    progress_callback,
                    "record_skipped",
                    "互动易问答知识抽取已完成，跳过重复处理",
                    total_items=total_records,
                    processed_items=idx,
                    success_count=totals["records"],
                    skipped_count=totals["skipped"],
                    fail_count=totals["fail"],
                    item_id=cninfo_id or None,
                    item_title=question[:200],
                    metadata={
                        "record_key": record_key,
                        "content_hash": content_hash,
                        "cached_entities": checkpoint.get("entities_count"),
                        "cached_relations": checkpoint.get("relations_count"),
                        "cached_result": cached_result,
                    },
                )
                continue

            await _mark_irm_running(rec, record_key, content_hash)
            result = await extract_irm_qa(
                question=question,
                answer=str(rec.get("answer") or rec.get("type") or ""),
                ts_code=str(rec.get("ts_code") or ""),
                company_name=str(rec.get("company_name") or rec.get("name") or rec.get("ts_code") or ""),
                cninfo_id=cninfo_id,
                ann_date=rec.get("ann_date"),
                progress_callback=progress_callback,
            )
            await _mark_irm_done(record_key, result)
            totals["records"] += 1
            totals["entities"] += result.get("entities_created", 0) + result.get("entities_updated", 0)
            totals["relations"] += result.get("relations_created", 0) + result.get("relations_updated", 0)
            totals["qa_vectors"] += int(bool(result.get("qa_vector_ok")))
            totals["entity_vectors"] += int(result.get("entity_vectors_ok", 0) or 0)
            totals["relation_vectors"] += int(result.get("relation_vectors_ok", 0) or 0)
            await _emit(
                progress_callback,
                "record_done",
                "互动易问答知识抽取完成",
                total_items=total_records,
                processed_items=idx,
                success_count=totals["records"],
                skipped_count=totals["skipped"],
                fail_count=totals["fail"],
                item_id=cninfo_id or None,
                item_title=question[:200],
                metadata={**result, "record_key": record_key, "content_hash": content_hash},
            )
        except Exception as exc:  # noqa: BLE001
            totals["fail"] += 1
            await _mark_irm_failed(record_key, str(exc))
            logger.warning("IRM record extraction failed: %s", exc)
            await _emit(
                progress_callback,
                "record_error",
                "互动易问答知识抽取失败",
                total_items=total_records,
                processed_items=idx,
                success_count=totals["records"],
                skipped_count=totals["skipped"],
                fail_count=totals["fail"],
                item_id=cninfo_id or None,
                item_title=question[:200],
                error=str(exc),
                metadata={"record_key": record_key, "content_hash": content_hash},
            )
    return totals
