# Data Readiness and Freshness Gate Design

## Context

QingShuiTouYan depends on daily external data to keep its knowledge base useful. K-line data, announcements, IR Q&A, news, and research reports feed Evidence, graph relations, vector search, and downstream reasoning. If these sources are stale or missing, the system can still run, but research conclusions can become invalid.

The current codebase already has pieces of a data reliability layer:

- `ingestion_runs`, `ingestion_checkpoints`, and `ingestion_jobs` track sync attempts and durable jobs.
- Domain tables such as `daily_data`, `announcements`, `research_report_meta`, and `events` hold local source records.
- The knowledge layer has Evidence and extraction jobs.

The missing product boundary is that Agent reasoning does not consistently know whether the local data is fresh enough for daily-reliable conclusions.

## Goal

Implement phase 1 and phase 2:

1. Add a local Data Readiness service that reports freshness and availability for key data domains.
2. Add an Agent freshness gate so research answers include data currency constraints and avoid strong conclusions when required sources are stale, missing, or failed.

This design does not refactor source connectors or rebuild the Evidence pipeline. It adds an audit and gating layer on top of the existing storage and sync metadata.

## Non-Goals

- Do not redesign `DataFetcher` or scheduler internals.
- Do not migrate announcement, IRM, news, or report ingestion into a new unified raw-record schema.
- Do not add a frontend dashboard in this phase.
- Do not implement automatic backfill or retry orchestration beyond using existing sync state.
- Do not block the entire API when data is stale. The gate should degrade reasoning, not make the system unavailable.

## Data Sources

The readiness service covers five source domains:

| Source | Display Name | Local Data Signal | Default Threshold |
| --- | --- | --- | --- |
| `kline` | K-line | max `daily_data.trade_date` | 1 trading day |
| `announcement` | Announcements | max non-IRM `announcements.ann_date` | 1 natural day |
| `irm` | IR Q&A | max `announcements.ann_date` where `announcement_type LIKE 'irm:%'` | 1 natural day |
| `news` | News | max `events.publish_at` | 1 natural day |
| `research_report` | Research Reports | max `research_report_meta.trade_date` | 3 natural days |

K-line uses a trading-day threshold because weekends and market holidays should not automatically make daily K-line stale. The first implementation may approximate trading days with weekdays and should isolate this logic in one helper so a real exchange calendar can replace it later.

## Readiness Model

Each source returns a normalized object:

```text
source: string
display_name: string
status: fresh | stale | missing | failed
latest_data_date: string | null
latest_success_at: string | null
lag_days: number | null
threshold_days: number
threshold_kind: natural_day | trading_day
coverage_scope: full_market | watchlist | portfolio | tech_mvp | unknown
required_for_reasoning: boolean
last_error: string | null
recommendation: string
```

Status semantics:

- `fresh`: local data exists and lag is within threshold.
- `stale`: local data exists, but lag exceeds threshold.
- `missing`: no local data exists for the source.
- `failed`: latest relevant sync metadata indicates failure and the data is stale or missing.

When data exists but the latest sync job failed, the service should prefer `stale` if the local data is current enough and include `last_error`. It should return `failed` only when the failure affects readiness.

## Sync Metadata

The service should use local data tables as the primary freshness signal and ingestion metadata as supporting context:

- `ingestion_runs`: latest run status, success time, current watermark, and error message.
- `ingestion_checkpoints`: last successful watermark and success timestamp.
- `ingestion_jobs`: pending, failed, dead, or running jobs for source-specific job types.

The first implementation may map sync metadata best-effort:

- `announcement`: source/task names containing `cninfo`, `announcement`, or `minishare_ann`.
- `irm`: source/task names containing `irm`.
- `kline`: source/task names containing `kline`.
- `news`: source/task names containing `news`.
- `research_report`: source/task names containing `report` or `research`.

This avoids requiring a migration before the feature is useful.

## API

Add two read APIs:

```text
GET /api/v1/readiness
GET /api/v1/readiness/{source}
```

`GET /api/v1/readiness` returns:

```text
{
  "as_of": "ISO timestamp",
  "overall_status": "fresh | degraded | unavailable",
  "sources": [...],
  "summary": "short human-readable summary"
}
```

Overall status:

- `fresh`: all required sources are `fresh`.
- `degraded`: at least one required source is `stale`, but none are `missing` or `failed`.
- `unavailable`: at least one required source is `missing` or `failed`.

The endpoint is read-only and should use optional API key behavior consistent with existing read endpoints.

## Agent Freshness Gate

The Agent should receive a readiness summary before answering research-style requests. The gate does not replace business logic; it constrains answer strength.

Rules:

- If all required sources are `fresh`, answer normally.
- If any required source is `stale`, answer must state the relevant data cutoff and avoid strong time-sensitive claims.
- If any required source is `missing` or `failed`, answer must not provide a strong conclusion. It should explain which source is unavailable and suggest syncing it first.
- When sources disagree, use the weakest required source status as the answer boundary.

The summary should be injected into the Agent context near the system/developer instruction layer, not appended as user-visible text by default. The Agent may still surface it when it affects the answer.

## Integration Point

Use a narrow integration point in the Agent API path rather than every individual tool:

1. The Agent request handler obtains `DataReadinessService.get_all()`.
2. It formats a compact freshness block.
3. It passes that block into the Agent runtime context or message builder.

This avoids touching every market, knowledge, and graph tool in phase 2. Tool-level gating can be added later if needed.

## Error Handling

Readiness checks must be fail-soft:

- If a single source query fails, mark that source `failed` with the exception message truncated for safety.
- If sync metadata lookup fails but source data lookup succeeds, keep the data status and include a metadata warning in `recommendation`.
- If all readiness checks fail due to database outage, the API returns `overall_status: unavailable`.

The Agent gate should treat readiness service failure as `unavailable` and avoid strong conclusions.

## Testing

Add focused tests for:

- Status calculation for fresh, stale, missing, and failed sources.
- K-line trading-day lag helper for weekday and weekend cases.
- API response shape and overall status aggregation.
- Agent freshness prompt/context formatting.
- Agent gate degradation text for stale or unavailable readiness.

Use dependency injection or monkeypatching for DB calls where possible so tests do not require live external data sources.

## Acceptance Criteria

- `GET /api/v1/readiness` returns normalized statuses for all five source domains.
- `GET /api/v1/readiness/{source}` returns one domain or a clear 404 for unknown sources.
- Readiness uses local database state only and never calls external data providers.
- Agent requests receive a compact freshness context.
- Stale or unavailable required sources prevent strong time-sensitive conclusions.
- Existing sync jobs, Evidence jobs, and data fetchers continue to work without behavior changes.
