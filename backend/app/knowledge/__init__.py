"""knowledge - 知识图谱构建."""

__all__ = ["EvidenceInput", "EvidenceService", "stable_evidence_id", "stable_job_id"]


def __getattr__(name: str):
    if name in {"EvidenceInput", "stable_evidence_id", "stable_job_id"}:
        from app.knowledge.evidence import EvidenceInput, stable_evidence_id, stable_job_id

        return {
            "EvidenceInput": EvidenceInput,
            "stable_evidence_id": stable_evidence_id,
            "stable_job_id": stable_job_id,
        }[name]
    if name == "EvidenceService":
        from app.knowledge.evidence_service import EvidenceService

        return EvidenceService
    raise AttributeError(name)
