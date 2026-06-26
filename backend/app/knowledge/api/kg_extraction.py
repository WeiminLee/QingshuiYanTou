"""
知识构建层 — KG 抽取 API

路由前缀：/api/v1/knowledge/kg
"""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.file_security import PathTraversalError, validate_file_path
from app.knowledge.kg_extractor import (
    extract_document,
    extract_text,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/knowledge/kg", tags=["知识构建层"])

# 允许的文件基准目录（Phase 31 D-C3 内部引用，与 kg_extractor.SAFE_BASE_DIR 含义相同）
SAFE_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


# ── Request / Response Models ─────────────────────────────


class ExtractTextRequest(BaseModel):
    text: str = Field(..., max_length=200_000, description="文本内容，最大20万字")
    ts_code: str = Field(..., max_length=20)
    source_name: str = Field(..., max_length=200)
    source_type: str = "uploaded_doc"
    article_ref: str = ""


class ExtractTextResponse(BaseModel):
    entities_created: int
    entities_updated: int
    relations_created: int
    relations_updated: int
    entities: list[str]
    relations: list[dict]
    chunks_processed: int


class ExtractDocumentRequest(BaseModel):
    file_path: str
    ts_code: str
    source_name: str
    source_type: str = "uploaded_doc"


# ── 路由 ───────────────────────────────────────────────


@router.post("/extract/text", response_model=ExtractTextResponse)
async def extract_text_api(req: ExtractTextRequest):
    """
    从文本直接抽取实体和关系，注入 Neo4j。

    实体类型：Company / Product / Event
    关系：自然语言描述，不枚举关系类型
    """
    if not req.text.strip():
        raise HTTPException(400, "文本内容为空")
    # 双重保护：Pydantic max_length 已限制，此处仅作兜底日志
    logger.debug(f"extract_text_api: text_len={len(req.text)}, ts_code={req.ts_code}")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: extract_text(
            text=req.text,
            ts_code=req.ts_code,
            source_name=req.source_name,
            source_type=req.source_type,
            article_ref=req.article_ref,
        ),
    )
    return ExtractTextResponse(**result)


@router.post("/extract/document", response_model=ExtractTextResponse)
async def extract_document_api(req: ExtractDocumentRequest, background: BackgroundTasks):
    """
    从 PDF/TXT 文件抽取实体和关系，注入 Neo4j。

    文件路径为绝对路径，必须对后端进程可读。
    建议通过前端上传后传入 uploads/ 目录下的路径。
    """
    try:
        safe_path = validate_file_path(Path(req.file_path), SAFE_BASE_DIR)
    except (ValueError, PathTraversalError) as e:
        raise HTTPException(400, f"不安全的文件路径: {e}")

    if not safe_path.exists():
        raise HTTPException(400, f"文件不存在: {req.file_path}")

    ext = safe_path.suffix.lower()
    if ext not in (".pdf", ".txt"):
        raise HTTPException(400, f"不支持的格式: {ext}，仅支持 PDF/TXT")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: extract_document(
                file_path=str(safe_path),
                ts_code=req.ts_code,
                source_name=req.source_name,
                source_type=req.source_type,
            ),
        )
        return ExtractTextResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("文档抽取失败: %s", req.file_path)
        raise HTTPException(500, f"抽取失败: {e}")


# ── KG 图谱统计 ────────────────────────────────────────


@router.get("/stats")
async def kg_stats():
    """获取 KG 图谱统计"""
    from app.core.neo4j_client import run

    loop = asyncio.get_event_loop()

    def _fetch():
        node_count = run("MATCH (n) RETURN count(n) AS cnt")[0]["cnt"]
        rel_count = run("MATCH ()-[r]->() RETURN count(r) AS cnt")[0]["cnt"]

        label_stats = run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY cnt DESC")
        rel_stats = run("MATCH ()-[r]->() RETURN type(r) AS rel_type, count(*) AS cnt ORDER BY cnt DESC")
        return node_count, rel_count, label_stats, rel_stats

    node_count, rel_count, label_stats, rel_stats = await loop.run_in_executor(None, _fetch)

    return {
        "total_nodes": node_count,
        "total_relations": rel_count,
        "by_label": [dict(r) for r in label_stats],
        "by_rel_type": [dict(r) for r in rel_stats],
    }


@router.get("/query")
async def kg_query(
    entity_type: str | None = Query(None),
    name_keyword: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """
    查询 KG 图谱节点

    - entity_type: Company / Product / Event
    - name_keyword: 名称模糊搜索
    """
    from app.knowledge.entity_service import query_entities

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: query_entities(entity_type=entity_type, name_keyword=name_keyword, limit=limit),
    )
    return result


@router.get("/relations")
async def kg_relations(
    from_entity: str | None = Query(None),
    to_entity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """
    查询 KG 关系

    - from_entity: 起始节点 entity_id 前缀
    - to_entity: 目标节点 entity_id 前缀
    """
    from app.knowledge.relation_service import query_relations

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: query_relations(from_entity=from_entity, to_entity=to_entity, limit=limit),
    )
    return result
