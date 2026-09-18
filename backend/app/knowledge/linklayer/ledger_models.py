# backend/app/knowledge/linklayer/ledger_models.py
"""判断台账（L2）：observation（观察·双源）/ finding（判断·派生）/ watermark（水位线·物化视图）。"""
import hashlib
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


def make_obs_id(evidence_id: str, subject: str, dimension: str, scope: str | None) -> str:
    """观察稳定 ID：hash(evidence_id + subject + dimension + scope)，同一锚点天然去重。"""
    raw = f"{evidence_id}|{subject}|{dimension}|{scope or ''}"
    return "OB:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def make_finding_id(subject: str, dimension: str, to_level: int, obs_ids: str) -> str:
    """判断稳定 ID：同一 (主体, 维度, to_level, 支撑观察集) 只落一条。"""
    return "FD:" + hashlib.sha256(f"{subject}|{dimension}|{to_level}|{obs_ids}".encode()).hexdigest()[:16]


# watermarks.dimension_scope 的哨兵值：复合主键不接受 NULL（且 NULL 不参与
# ON CONFLICT 匹配），"无 scope" 统一归一化为空串。
SCOPE_SENTINEL = ""


def normalize_scope(scope: str | None) -> str:
    """dimension_scope 归一化：None/'' → 哨兵空串。"""
    return scope if scope else SCOPE_SENTINEL


class Observation(Base):
    """观察记录。status ∈ candidate(机械) | verified(agent) | dismissed；written_by = pipeline | agent:<run_id>"""

    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("obs_id", name="uq_observations_obs_id"),
        Index("idx_observations_subject", "subject_ts_code", "dimension", "dimension_scope"),
        Index("idx_observations_evidence", "evidence_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    obs_id: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    subject_name: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    dimension_scope: Mapped[str | None] = mapped_column(Text)
    stage_raw: Mapped[str | None] = mapped_column(Text)
    stage_level: Mapped[int | None] = mapped_column(Integer)
    metric_value: Mapped[dict | None] = mapped_column(JSONB)  # {num, unit, period, metric}
    evidence_id: Mapped[str] = mapped_column(Text, nullable=False)
    span_start: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    span_end: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    event_date: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    written_by: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="candidate")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Finding(Base):
    """判断（spec §4.3 修订 3：supports 必须句级锚定）。"""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("finding_id", name="uq_findings_finding_id"),
        Index("idx_findings_subject", "subject_ts_code", "dimension"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # progression|regression|new_event|association|divergence
    subject_ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    dimension_scope: Mapped[str | None] = mapped_column(Text)
    from_state: Mapped[dict | None] = mapped_column(JSONB)
    to_state: Mapped[dict | None] = mapped_column(JSONB)
    delta: Mapped[dict | None] = mapped_column(JSONB)
    supports: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{obs_id, evidence_id, span_start, span_end}]
    contradicts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    judgment: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="candidate")
    supersedes: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Watermark(Base):
    """水位线（spec §5.2）：雷达消费者用它过滤 delta，judge 不过滤。"""

    __tablename__ = "watermarks"

    subject_ts_code: Mapped[str] = mapped_column(Text, primary_key=True)
    dimension: Mapped[str] = mapped_column(Text, primary_key=True)
    dimension_scope: Mapped[str] = mapped_column(Text, primary_key=True, server_default=SCOPE_SENTINEL)
    max_level: Mapped[int | None] = mapped_column(Integer)
    max_value: Mapped[dict | None] = mapped_column(JSONB)
    first_reached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
