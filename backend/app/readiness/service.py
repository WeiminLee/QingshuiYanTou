from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Mapping, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database import engine
from app.readiness.schemas import ReadinessSource, ReadinessSummary, SourceStatus, ThresholdKind

logger = logging.getLogger(__name__)
SH_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class SourceSpec:
    source: str
    display_name: str
    threshold_days: int
    threshold_kind: ThresholdKind
    coverage_scope: str = "unknown"
    required_for_reasoning: bool = True


@dataclass(frozen=True)
class SourceSyncSnapshot:
    latest_success_at: datetime | None = None
    latest_attempt_at: datetime | None = None
    latest_status: str | None = None
    last_error: str | None = None
    unresolved_failure: bool = False


@dataclass(frozen=True)
class SourceDataSnapshot:
    source: str
    latest_data_date: date | None
    sync: SourceSyncSnapshot


class ReadinessRepository(Protocol):
    async def get_latest_data_date(self, source: str) -> date | None:
        ...

    async def get_sync_snapshot(self, source: str) -> SourceSyncSnapshot:
        ...


SOURCE_SPECS: dict[str, SourceSpec] = {
    "kline": SourceSpec("kline", "K-line", 1, ThresholdKind.TRADING_DAY, "unknown", True),
    "announcement": SourceSpec("announcement", "Announcements", 1, ThresholdKind.NATURAL_DAY, "unknown", True),
    "irm": SourceSpec("irm", "IR Q&A", 1, ThresholdKind.NATURAL_DAY, "unknown", True),
    "news": SourceSpec("news", "News", 1, ThresholdKind.NATURAL_DAY, "unknown", True),
    "research_report": SourceSpec(
        "research_report",
        "Research Reports",
        3,
        ThresholdKind.NATURAL_DAY,
        "unknown",
        True,
    ),
}

SYNC_ACQUISITION_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "kline": (("kline", "kline"), ("tushare", "kline")),
    "announcement": (
        ("cninfo", "announcements"),
        ("cninfo", "announcements_history"),
        ("minishare_ann", "ann_history"),
    ),
    "irm": (("irm", "qa_fetch"), ("irm_minishare", "irm_daily_backfill")),
    "news": (("news", "news"), ("akshare", "news")),
    "research_report": (("minishare", "reports_history"),),
}

MONITOR_TASK_NAMES: dict[str, tuple[str, ...]] = {
    "kline": ("kline",),
    "announcement": ("cninfo", "cninfo_enqueue"),
    "irm": ("irm", "irm_enqueue"),
    "news": ("news", "news_sync"),
    "research_report": ("reports",),
}

INGESTION_JOB_TYPES: dict[str, tuple[str, ...]] = {
    "announcement": ("cninfo_announcement_date",),
    "irm": ("irm_company",),
}


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SH_TZ).astimezone(UTC)
    return value.astimezone(UTC)


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SH_TZ)
    return value.astimezone(SH_TZ)


def count_weekday_lag(latest: date, current: date) -> int:
    if latest >= current:
        return 0
    days = 0
    probe = latest
    while probe < current:
        probe = date.fromordinal(probe.toordinal() + 1)
        if probe.weekday() < 5:
            days += 1
    return days


def build_sync_query(source: str):
    """Build a source-specific acquisition-run query and its bound parameters."""
    pairs = SYNC_ACQUISITION_PAIRS.get(source, ())
    if not pairs:
        return text("SELECT NULL WHERE FALSE"), {}

    clauses = []
    params = {}
    for index, (run_source, task_name) in enumerate(pairs):
        source_param = f"source_{index}"
        task_param = f"task_{index}"
        params[source_param] = run_source
        params[task_param] = task_name
        clauses.append(
            f"(LOWER(source) = :{source_param} AND LOWER(task_name) = :{task_param})"
        )
    where = " OR ".join(clauses)
    return text(
        f"""
        SELECT status, completed_at, last_error,
               MAX(completed_at) FILTER (WHERE status = 'success') OVER () AS latest_success_at,
               COALESCE(updated_at, completed_at, started_at) AS latest_attempt_at
        FROM ingestion_runs
        WHERE {where}
        ORDER BY updated_at DESC NULLS LAST, started_at DESC NULLS LAST
        LIMIT 1
        """
    ), params


def build_monitor_query(source: str):
    """Build a sync_task_status query for scheduler-recorded daily tasks."""
    task_names = MONITOR_TASK_NAMES.get(source, ())
    if not task_names:
        return text("SELECT NULL WHERE FALSE"), {}

    params = {f"task_{index}": task_name for index, task_name in enumerate(task_names)}
    placeholders = ", ".join(f":task_{index}" for index in range(len(task_names)))
    return text(
        f"""
        SELECT status, completed_at, error_message AS last_error,
               MAX(completed_at) FILTER (WHERE status IN ('success', 'partial')) OVER () AS latest_success_at,
               COALESCE(updated_at, completed_at, started_at) AS latest_attempt_at
        FROM sync_task_status
        WHERE LOWER(task_name) IN ({placeholders})
        ORDER BY updated_at DESC NULLS LAST, started_at DESC NULLS LAST
        LIMIT 1
        """
    ), params


def build_ingestion_jobs_query(source: str):
    """Build an ingestion_jobs query for durable queued acquisition work."""
    job_types = INGESTION_JOB_TYPES.get(source, ())
    if not job_types:
        return text("SELECT NULL WHERE FALSE"), {}

    params = {f"job_type_{index}": job_type for index, job_type in enumerate(job_types)}
    placeholders = ", ".join(f":job_type_{index}" for index in range(len(job_types)))
    return text(
        f"""
        WITH job_rows AS (
            SELECT id, status, updated_at, last_error
            FROM ingestion_jobs
            WHERE job_type IN ({placeholders})
        ),
        latest_success AS (
            SELECT MAX(updated_at) AS latest_success_at
            FROM job_rows
            WHERE status IN ('success', 'partial')
        ),
        latest_failure AS (
            SELECT status, updated_at AS completed_at, last_error,
                   updated_at AS latest_attempt_at
            FROM job_rows
            WHERE status IN ('failed', 'dead')
            ORDER BY updated_at DESC NULLS LAST, id DESC
            LIMIT 1
        ),
        latest_attempt AS (
            SELECT status, updated_at AS completed_at, last_error,
                   updated_at AS latest_attempt_at
            FROM job_rows
            ORDER BY updated_at DESC NULLS LAST, id DESC
            LIMIT 1
        )
        SELECT COALESCE(f.status, a.status) AS status,
               COALESCE(f.completed_at, a.completed_at) AS completed_at,
               COALESCE(f.last_error, a.last_error) AS last_error,
               s.latest_success_at,
               COALESCE(f.latest_attempt_at, a.latest_attempt_at) AS latest_attempt_at,
               (f.status IS NOT NULL) AS unresolved_failure
        FROM latest_success s
        LEFT JOIN latest_failure f ON TRUE
        LEFT JOIN latest_attempt a ON TRUE
        WHERE f.status IS NOT NULL
           OR a.status IS NOT NULL
           OR s.latest_success_at IS NOT NULL
        LIMIT 1
        """
    ), params


def build_checkpoint_query(source: str):
    """Build an ingestion_checkpoints query for checkpoint-backed sync state."""
    pairs = SYNC_ACQUISITION_PAIRS.get(source, ())
    if not pairs:
        return text("SELECT NULL WHERE FALSE"), {}

    clauses = []
    params = {}
    for index, (run_source, task_name) in enumerate(pairs):
        source_param = f"checkpoint_source_{index}"
        task_param = f"checkpoint_task_{index}"
        params[source_param] = run_source
        params[task_param] = task_name
        clauses.append(
            f"(LOWER(source) = :{source_param} AND LOWER(task_name) = :{task_param})"
        )
    where = " OR ".join(clauses)
    return text(
        f"""
        WITH checkpoint_rows AS (
            SELECT id, last_status, last_success_at, last_attempt_at, updated_at
            FROM ingestion_checkpoints
            WHERE {where}
        ),
        latest_success AS (
            SELECT MAX(last_success_at) AS latest_success_at
            FROM checkpoint_rows
        ),
        latest_failure AS (
            SELECT last_status AS status, last_attempt_at AS completed_at,
                   NULL::text AS last_error, last_attempt_at AS latest_attempt_at
            FROM checkpoint_rows
            WHERE last_status IN ('failed', 'dead')
            ORDER BY last_attempt_at DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC
            LIMIT 1
        ),
        latest_attempt AS (
            SELECT last_status AS status, last_attempt_at AS completed_at,
                   NULL::text AS last_error, last_attempt_at AS latest_attempt_at
            FROM checkpoint_rows
            ORDER BY last_attempt_at DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC
            LIMIT 1
        )
        SELECT COALESCE(f.status, a.status) AS status,
               COALESCE(f.completed_at, a.completed_at) AS completed_at,
               COALESCE(f.last_error, a.last_error) AS last_error,
               s.latest_success_at,
               COALESCE(f.latest_attempt_at, a.latest_attempt_at) AS latest_attempt_at,
               (f.status IS NOT NULL) AS unresolved_failure
        FROM latest_success s
        LEFT JOIN latest_failure f ON TRUE
        LEFT JOIN latest_attempt a ON TRUE
        WHERE f.status IS NOT NULL
           OR a.status IS NOT NULL
           OR s.latest_success_at IS NOT NULL
        LIMIT 1
        """
    ), params


def source_sync_snapshot_from_row(row: Mapping[str, object]) -> SourceSyncSnapshot:
    """Normalize the newest matching run and its historical success timestamp."""
    status = row.get("status")
    completed_at = row.get("completed_at")
    latest_success_at = row.get("latest_success_at")
    latest_attempt_at = row.get("latest_attempt_at")
    if latest_success_at is None and status == "success":
        latest_success_at = completed_at
    return SourceSyncSnapshot(
        latest_success_at=_as_utc(latest_success_at) if isinstance(latest_success_at, datetime) else None,
        latest_attempt_at=_as_utc(latest_attempt_at) if isinstance(latest_attempt_at, datetime) else None,
        latest_status=status if isinstance(status, str) else None,
        last_error=row.get("last_error") if isinstance(row.get("last_error"), str) else None,
        unresolved_failure=row.get("unresolved_failure") is True,
    )


def merge_sync_snapshots(snapshots: list[SourceSyncSnapshot]) -> SourceSyncSnapshot:
    """Merge multiple local sync metadata sources into one readiness snapshot."""
    present = [
        snapshot
        for snapshot in snapshots
        if snapshot.latest_status or snapshot.latest_success_at or snapshot.last_error
    ]
    if not present:
        return SourceSyncSnapshot()

    latest_success_at = None
    for snapshot in present:
        if snapshot.latest_success_at and (
            latest_success_at is None or snapshot.latest_success_at > latest_success_at
        ):
            latest_success_at = snapshot.latest_success_at

    metadata_warnings = [
        snapshot.last_error
        for snapshot in present
        if snapshot.last_error
        and "lookup failed" in snapshot.last_error
        and snapshot.latest_status is None
        and snapshot.latest_attempt_at is None
        and snapshot.latest_success_at is None
    ]
    operational = [
        snapshot
        for snapshot in present
        if snapshot.latest_status or snapshot.latest_success_at or snapshot.latest_attempt_at
    ]
    unresolved_failures = [
        snapshot
        for snapshot in operational
        if snapshot.unresolved_failure and snapshot.latest_status in {"failed", "dead"}
    ]
    newest_pool = unresolved_failures or operational or present
    newest = max(
        newest_pool,
        key=lambda snapshot: snapshot.latest_attempt_at or snapshot.latest_success_at or datetime.min.replace(tzinfo=UTC),
    )
    latest_status = newest.latest_status
    last_error = newest.last_error
    warning_text = "; ".join(dict.fromkeys(metadata_warnings))
    if warning_text:
        last_error = f"{last_error}; {warning_text}" if last_error else warning_text
        last_error = last_error[:300]

    return SourceSyncSnapshot(
        latest_success_at=latest_success_at,
        latest_attempt_at=newest.latest_attempt_at,
        latest_status=latest_status,
        last_error=last_error,
        unresolved_failure=newest.unresolved_failure,
    )


class SqlReadinessRepository:
    async def get_latest_data_date(self, source: str) -> date | None:
        sql_by_source = {
            "kline": "SELECT MAX(trade_date) FROM daily_data",
            "announcement": (
                "SELECT MAX(ann_date) FROM announcements "
                "WHERE announcement_type IS NULL OR announcement_type NOT LIKE 'irm:%%'"
            ),
            "irm": "SELECT MAX(ann_date) FROM announcements WHERE announcement_type LIKE 'irm:%%'",
            "news": "SELECT MAX(DATE(publish_at AT TIME ZONE 'Asia/Shanghai')) FROM events",
            "research_report": "SELECT MAX(trade_date) FROM research_report_meta",
        }
        sql = sql_by_source.get(source)
        if not sql:
            return None
        async with engine.connect() as conn:
            result = await conn.execute(text(sql))
            value = result.scalar()
        if isinstance(value, datetime):
            return value.date()
        return value

    async def get_sync_snapshot(self, source: str) -> SourceSyncSnapshot:
        snapshots = []
        sql, params = build_sync_query(source)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(sql, params)
                row = result.mappings().first()
        except Exception as exc:
            logger.warning("[Readiness] sync metadata lookup failed for %s: %s", source, exc)
            snapshots.append(SourceSyncSnapshot(last_error=f"sync metadata lookup failed: {str(exc)[:300]}"))
        else:
            snapshots.append(source_sync_snapshot_from_row(row) if row else SourceSyncSnapshot())

        monitor_sql, monitor_params = build_monitor_query(source)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(monitor_sql, monitor_params)
                row = result.mappings().first()
        except Exception as exc:
            logger.warning("[Readiness] monitor metadata lookup failed for %s: %s", source, exc)
            snapshots.append(SourceSyncSnapshot(last_error=f"sync monitor lookup failed: {str(exc)[:300]}"))
        else:
            snapshots.append(source_sync_snapshot_from_row(row) if row else SourceSyncSnapshot())

        jobs_sql, jobs_params = build_ingestion_jobs_query(source)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(jobs_sql, jobs_params)
                row = result.mappings().first()
        except Exception as exc:
            logger.warning("[Readiness] ingestion job metadata lookup failed for %s: %s", source, exc)
            snapshots.append(SourceSyncSnapshot(last_error=f"sync job lookup failed: {str(exc)[:300]}"))
        else:
            snapshots.append(source_sync_snapshot_from_row(row) if row else SourceSyncSnapshot())

        checkpoint_sql, checkpoint_params = build_checkpoint_query(source)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(checkpoint_sql, checkpoint_params)
                row = result.mappings().first()
        except Exception as exc:
            logger.warning("[Readiness] checkpoint metadata lookup failed for %s: %s", source, exc)
            snapshots.append(SourceSyncSnapshot(last_error=f"sync checkpoint lookup failed: {str(exc)[:300]}"))
        else:
            snapshots.append(source_sync_snapshot_from_row(row) if row else SourceSyncSnapshot())

        return merge_sync_snapshots(snapshots)


class DataReadinessService:
    def __init__(self, repository: ReadinessRepository | None = None):
        self.repository = repository or SqlReadinessRepository()

    async def get_all(self, now: datetime | None = None) -> ReadinessSummary:
        as_of = _as_shanghai(now or _now_utc())
        snapshots: list[SourceDataSnapshot] = []
        for source in SOURCE_SPECS:
            snapshots.append(await self._load_snapshot(source))
        return self.build_summary(as_of, snapshots)

    async def get_source(self, source: str, now: datetime | None = None) -> ReadinessSource | None:
        if source not in SOURCE_SPECS:
            return None
        as_of = _as_shanghai(now or _now_utc())
        summary = self.build_summary(as_of, [await self._load_snapshot(source)])
        return summary.sources[0]

    async def _load_snapshot(self, source: str) -> SourceDataSnapshot:
        try:
            latest = await self.repository.get_latest_data_date(source)
        except Exception as exc:
            logger.warning("[Readiness] data lookup failed for %s: %s", source, exc)
            return SourceDataSnapshot(
                source=source,
                latest_data_date=None,
                sync=SourceSyncSnapshot(latest_status="failed", last_error=str(exc)[:300]),
            )
        try:
            sync = await self.repository.get_sync_snapshot(source)
        except Exception as exc:
            logger.warning("[Readiness] sync lookup failed for %s: %s", source, exc)
            sync = SourceSyncSnapshot(last_error=str(exc)[:300])
        return SourceDataSnapshot(source=source, latest_data_date=latest, sync=sync)

    def build_summary(self, now: datetime, sources: list[SourceDataSnapshot]) -> ReadinessSummary:
        as_of = _as_shanghai(now)
        items = [self._build_source(as_of, snapshot) for snapshot in sources]
        overall = self._overall_status(items)
        stale_count = sum(1 for item in items if item.status == SourceStatus.STALE)
        unavailable_count = sum(1 for item in items if item.status in {SourceStatus.MISSING, SourceStatus.FAILED})
        if overall == "fresh":
            summary = "全部关键数据源处于日级可靠窗口内。"
        elif overall == "degraded":
            summary = f"{stale_count} 个关键数据源已滞后，Agent 结论需要声明数据截至日期。"
        else:
            summary = f"{unavailable_count} 个关键数据源缺失或失败，Agent 不应给出强时效结论。"
        return ReadinessSummary(
            as_of=as_of.isoformat(),
            overall_status=overall,
            sources=items,
            summary=summary,
        )

    def _build_source(self, now: datetime, snapshot: SourceDataSnapshot) -> ReadinessSource:
        spec = SOURCE_SPECS[snapshot.source]
        latest = snapshot.latest_data_date
        lag_days: int | None = None
        if latest is None:
            status = SourceStatus.MISSING
            recommendation = "本地没有该数据源记录，需要先完成同步。"
        else:
            current_date = _as_shanghai(now).date()
            if spec.threshold_kind == ThresholdKind.TRADING_DAY:
                lag_days = count_weekday_lag(latest, current_date)
            else:
                lag_days = max(0, (current_date - latest).days)
            if lag_days <= spec.threshold_days:
                status = SourceStatus.FRESH
                recommendation = "数据处于日级可靠窗口内。"
            else:
                status = SourceStatus.STALE
                recommendation = f"数据已滞后 {lag_days} 天，回答需要声明基于截至 {latest.isoformat()} 的数据。"
        last_error = snapshot.sync.last_error
        if last_error and len(last_error) > 300:
            last_error = last_error[:300]
        if snapshot.sync.latest_status in {"failed", "dead"}:
            if status == SourceStatus.FRESH:
                status = SourceStatus.STALE
                recommendation = "最近同步失败；虽然本地数据仍在日级窗口内，回答需要降低结论强度并提示先确认同步。"
            elif status in {SourceStatus.STALE, SourceStatus.MISSING}:
                status = SourceStatus.FAILED
                recommendation = "最近同步失败，回答前应先修复并同步该数据源。"
        elif last_error and "lookup failed" in last_error:
            recommendation = f"{recommendation} 同步元数据查询失败，需人工确认最近同步状态。"
        return ReadinessSource(
            source=spec.source,
            display_name=spec.display_name,
            status=status,
            latest_data_date=latest.isoformat() if latest else None,
            latest_success_at=(
                _as_utc(snapshot.sync.latest_success_at).isoformat()
                if snapshot.sync.latest_success_at
                else None
            ),
            lag_days=lag_days,
            threshold_days=spec.threshold_days,
            threshold_kind=spec.threshold_kind,
            coverage_scope=spec.coverage_scope,
            required_for_reasoning=spec.required_for_reasoning,
            last_error=last_error,
            recommendation=recommendation,
        )

    def _overall_status(self, items: list[ReadinessSource]) -> str:
        required = [item for item in items if item.required_for_reasoning]
        if any(item.status in {SourceStatus.MISSING, SourceStatus.FAILED} for item in required):
            return "unavailable"
        if any(item.status == SourceStatus.STALE for item in required):
            return "degraded"
        return "fresh"


def format_readiness_for_agent(summary: ReadinessSummary) -> str:
    lines = [
        "<data_readiness>",
        f"as_of={summary.as_of}",
        f"overall_status={summary.overall_status}",
        "rules:",
        "- fresh: 可以正常回答。",
        "- stale: 必须声明基于截至日期的数据，并降低结论强度。",
        "- missing/failed: 不得给出强时效结论，应提示先同步对应数据。",
        "sources:",
    ]
    for item in summary.sources:
        cutoff = item.latest_data_date or "none"
        detail = (
            f"- {item.source}: {item.status.value}; latest_data_date={cutoff}; "
            f"lag_days={item.lag_days}; threshold={item.threshold_days} {item.threshold_kind.value}; "
            f"recommendation={item.recommendation}"
        )
        if item.last_error:
            detail += f"; last_error={item.last_error}"
        lines.append(detail)
    if summary.overall_status == "degraded":
        lines.append("answer_boundary=基于截至最新可用日期的数据，避免强时效判断。")
    elif summary.overall_status == "unavailable":
        lines.append("answer_boundary=关键数据缺失或同步失败，不得输出强结论。")
    else:
        lines.append("answer_boundary=关键数据源处于日级可靠窗口内。")
    lines.append("</data_readiness>")
    return "\n".join(lines)
