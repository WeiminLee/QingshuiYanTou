"""Read-only 文档聚合视图 HTTP（artifact reader）。

按 ``ann_id`` 聚合 ``kg_evidence`` 章节行，返回文档元信息与章节清单（不含正文）。
只读：不写库；响应永不含服务器路径（``pdf`` 只报 ``exists``/``sha256``/``size``）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.core.mongodb import get_mongo_db
from app.knowledge.api._auth import require_api_key
from app.knowledge.document_service import load_document

router = APIRouter(prefix="/api/v1/knowledge/documents", tags=["知识 文档"])


@router.get("/{ann_id}")
async def get_document(
    ann_id: str,
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_api_key(x_api_key)
    document = await load_document(
        get_mongo_db(),
        ann_id,
        root=settings.pdf_storage_root,
    )
    if document is None:
        raise HTTPException(404, detail={"code": "document_not_found"})
    return document
