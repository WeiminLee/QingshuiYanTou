"""
knowledge - 知识图谱构建

子模块：
- api: REST API
- extraction: 知识抽取
- ingestion: 文档摄取
- kg_extractor: 实体抽取
- relation_service: 关系服务
- vector_client: 向量存储
"""

from app.knowledge.evidence import EvidenceInput, stable_evidence_id, stable_job_id
from app.knowledge.evidence_service import EvidenceService

__all__ = [
    "EvidenceInput",
    "EvidenceService",
    "stable_evidence_id",
    "stable_job_id",
]
