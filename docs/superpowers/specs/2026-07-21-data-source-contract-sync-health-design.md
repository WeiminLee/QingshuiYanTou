# Data Source Contract and Sync Health Design

## Context

Phase 1/2 added a local Data Readiness service and Agent freshness gate. The system can now tell the Agent whether K-line, announcements, IR Q&A, news, and research reports are fresh enough for daily-reliable reasoning.

The remaining weakness is that source metadata is still scattered:

- Readiness owns source thresholds and table signals.
- Scheduler and monitor own task names such as `kline`, `cninfo_enqueue`, `irm_enqueue`, `news_sync`, and `reports`.
- Durable queue producers own `ingestion_jobs.job_type` values.
- `IngestionProgressTracker` owns checkpoint `source/task_name/scope` values.

This works, but it makes source reliability hard to operate. A source's expected schedule, tolerated lag, job dependencies, and checkpoint dependencies should be declared in one local contract and consumed by readiness and future sync-health tooling.

## Goal

Implement phase 3 as a small governance layer:

1. Add a local Data Source Contract registry for the five daily-reliable source domains.
2. Refactor readiness to consume that registry instead of keeping separate hard-coded source metadata maps.
3. Add a Sync Health summary API that reports each source's configured sync dependencies and observed local sync state.

The result should make it obvious what each source depends on and whether its sync chain is healthy enough to support daily-reliable conclusions.

## Non-Goals

- Do not replace scheduler, job queue, or `IngestionProgressTracker`.
- Do not migrate existing tables or introduce a new database source-of-truth table in this phase.
- Do not add external providers or call external networks from readiness or sync-health code.
- Do not implement automatic repair, backfill orchestration, or retry policy changes.
- Do not add a frontend dashboard in this phase.
- Do not change Agent prompt behavior beyond preserving the existing freshness gate.

## Source Contract Model

Each source domain is declared with a stable contract:

```text
source: kline | announcement | irm | news | research_report
display_name: string
description: string
update_frequency: intraday | daily | periodic
expected_arrival: string
threshold_days: number
threshold_kind: natural_day | trading_day
coverage_scope: full_market | watchlist | portfolio | tech_mvp | unknown
required_for_reasoning: boolean
local_data_signal: string
monitor_tasks: list[string]
acquisition_tasks: list[{source: string, task_name: string}]
job_types: list[string]
checkpoint_tasks: list[{source: string, task_name: string}]
owner_module: string
```

The first implementation should use an in-code registry, not YAML or a database table. This keeps deployment simple and avoids adding configuration parsing before the contract stabilizes. The registry should live in a dedicated module so a later YAML/database-backed implementation can replace it without changing readiness consumers.

## Initial Contracts

The registry covers the same five required sources as the readiness service:

| Source | Expected Arrival | Threshold | Local Data Signal | Monitor Tasks | Job Types | Checkpoints |
| --- | --- | --- | --- | --- | --- | --- |
| `kline` | trading day close + local sync | 1 trading day | `daily_data.trade_date` | `kline` | none | `kline/kline`, `tushare/kline` |
| `announcement` | daily after close | 1 natural day | non-IRM `announcements.ann_date` | `cninfo`, `cninfo_enqueue` | `cninfo_announcement_date` | `cninfo/announcements`, `cninfo/announcements_history`, `minishare_ann/ann_history` |
| `irm` | daily evening | 1 natural day | IRM rows in `announcements.ann_date` | `irm`, `irm_enqueue` | `irm_company` | `irm/qa_fetch`, `irm_minishare/irm_daily_backfill` |
| `news` | every 5 minutes | 1 natural day | `events.publish_at` | `news`, `news_sync` | none | `news/news`, `akshare/news` |
| `research_report` | daily early morning | 3 natural days | `research_report_meta.trade_date` | `reports` | none | `minishare/reports_history` |

The exact expected-arrival values are descriptive strings in phase 3. They should not drive scheduling until a later phase adds active SLA enforcement.

## Sync Health Model

Add a normalized sync-health response that is contract-centered rather than readiness-centered:

```text
source: string
display_name: string
overall: healthy | degraded | failed | unknown
contract: {
  expected_arrival: string
  threshold_days: number
  threshold_kind: natural_day | trading_day
  monitor_tasks: list[string]
  job_types: list[string]
  checkpoint_tasks: list[string]
}
latest_success_at: string | null
latest_attempt_at: string | null
latest_status: string | null
unresolved_failure: boolean
last_error: string | null
readiness_status: fresh | stale | missing | failed
recommendation: string
```

Health semantics:

- `healthy`: readiness is `fresh`, latest sync state has no unresolved failure, and no metadata lookup warning exists.
- `degraded`: readiness is `stale` or metadata lookup warnings exist, but no unresolved failed/dead job is visible.
- `failed`: readiness is `failed` or sync metadata shows unresolved failed/dead work.
- `unknown`: readiness or sync metadata cannot be loaded enough to classify the source.

This summary is an operator view. Agent gating should continue to use the existing readiness summary.

## API

Add read-only endpoints under the existing readiness router:

```text
GET /api/v1/readiness/contracts
GET /api/v1/readiness/sync-health
GET /api/v1/readiness/sync-health/{source}
```

`GET /api/v1/readiness/contracts` returns the configured contracts without live DB state.

`GET /api/v1/readiness/sync-health` returns one health object per source.

`GET /api/v1/readiness/sync-health/{source}` returns one health object or `404` for an unknown source.

The endpoints should follow the same optional API-key behavior as the existing readiness endpoints through the already-mounted router.

## Architecture

Create a small `app.readiness.contracts` module with:

- `DataSourceContract` dataclass.
- `AcquisitionTaskRef` dataclass.
- `get_contract(source: str) -> DataSourceContract | None`.
- `list_contracts() -> tuple[DataSourceContract, ...]`.

Update `app.readiness.service` so `SourceSpec`, acquisition task pairs, monitor task names, and job types are derived from contracts. Keep SQL-building helpers public where tests already import them.

Add a `SyncHealthService` in a new `app.readiness.sync_health` module. It should reuse the existing repository and readiness service instead of duplicating data-date queries. For phase 3, the service may classify health from the merged `SourceSyncSnapshot` and `ReadinessSource` already produced by readiness.

## Error Handling

Contract loading is static and should not fail at runtime unless code is invalid.

Sync-health DB access must be fail-soft:

- If readiness for a source fails, return `overall: unknown` for that source with a bounded `last_error`.
- If sync metadata lookup fails but readiness data is available, return `overall: degraded` and include the metadata warning.
- If an unknown source is requested, return `404`.

Error strings exposed through APIs should be bounded to 300 characters.

## Testing

Add focused tests for:

- Contract registry contains all five required sources.
- Contract registry exposes monitor tasks, acquisition tasks, job types, and checkpoint tasks for announcement and IRM.
- Existing readiness query builders derive their mappings from contracts.
- Contract endpoint response shape.
- Sync-health classification for healthy, degraded, failed, and unknown sources using fake services/repositories.
- Unknown sync-health source returns `404`.

Tests should not require external data providers or a live network. Prefer fake repositories and monkeypatching over database setup.

## Acceptance Criteria

- All five daily-reliable sources are declared in one contract registry.
- Readiness source specs and sync metadata mappings are derived from the contract registry.
- `GET /api/v1/readiness/contracts` returns all configured contracts.
- `GET /api/v1/readiness/sync-health` returns a normalized health summary for all sources.
- `GET /api/v1/readiness/sync-health/{source}` returns one source or a clear `404`.
- No scheduler, fetcher, job queue, or Agent prompt behavior is changed in this phase.
- Existing readiness and Agent freshness tests continue to pass.
