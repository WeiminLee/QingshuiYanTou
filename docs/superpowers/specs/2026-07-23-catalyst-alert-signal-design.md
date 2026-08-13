# Future Catalyst Alert Signal Design

**Date:** 2026-07-23
**Scope:** Add P0 future catalyst / event alert signals for SignalRadar and AgentContext.
**Decision:** Use a separate `CatalystEvent` fact layer and generate `catalyst` signals into the existing signal consumption surface.
**Status:** Design spec for implementation planning.

---

## 1. Background

The existing signal system focuses on information that has already happened: announcements, IRM replies, news, research reports, evidence, and market anomalies. These sources answer:

```text
What happened, and what does it imply?
```

The product also needs a distinct early-warning capability:

```text
What important events will happen soon, what themes or companies could they affect, and does this hit the user's holdings or interests?
```

Examples include earnings releases, investor days, overseas developer conferences, industry exhibitions, policy windows, macro data releases, and major product launches.

This is not the same as an observed signal. A future event is a scheduled fact; the alert signal is the interpreted warning generated from it.

## 2. Goals

- Add a `CatalystEvent` layer for future event facts.
- Generate `catalyst` signals that are compatible with the existing SignalRadar and AgentContext flows.
- Support a P0 five-day future window.
- Match events to KG subjects, 2-hop propagation targets, user portfolio, watchlist, and preferences.
- Run without external data source dependencies by using fixtures.
- Keep a provider interface ready for real calendar, earnings, exchange, company IR, policy, or conference sources.

## 3. Non-Goals

- Do not build a full real-time push notification system.
- Do not depend on paid or unstable external calendar APIs for P0.
- Do not make trading recommendations.
- Do not use LLM-only judgment for event impact in P0.
- Do not implement post-event replay or outcome review in P0.
- Do not wait for the Observation -> Signal model redesign before shipping this feature.

## 4. Architecture

P0 uses a two-layer model:

```text
Fixture / CalendarProvider
  -> CatalystEventStore
  -> CatalystSignalBuilder
  -> KG / theme mapping / 2-hop propagation
  -> UserHitMatcher
  -> signals(signal_kind=catalyst)
  -> SignalRadar + AgentContext
```

`CatalystEvent` answers: "what future event exists?"

`CatalystSignal` answers: "why should this event be surfaced to this market/user context?"

Physically, P0 stores alert signals in the existing `signals` table with `signal_kind='catalyst'`. The event fact remains separate in `catalyst_events`.

This choice avoids creating a third user-facing signal surface while preserving clean event lifecycle and source provenance.

## 5. Data Model

### 5.1 `catalyst_events`

Create a PostgreSQL table:

```text
catalyst_events
- id BIGSERIAL PK
- event_id VARCHAR(40) UNIQUE NOT NULL
- event_type VARCHAR(40) NOT NULL
- title TEXT NOT NULL
- event_date DATE NOT NULL
- event_time TIME
- timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai'
- source_type VARCHAR(40) NOT NULL
- source_id VARCHAR(128)
- source_url TEXT
- importance INTEGER NOT NULL
- subjects JSONB NOT NULL DEFAULT '[]'
- status VARCHAR(24) NOT NULL DEFAULT 'scheduled'
- metadata JSONB NOT NULL DEFAULT '{}'
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
- updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
```

Allowed `event_type` values for P0:

```text
earnings_release
conference
product_launch
policy_window
industry_expo
macro_data
other
```

Allowed `source_type` values for P0:

```text
fixture
calendar
exchange
company_ir
policy_calendar
conference_calendar
```

Allowed `status` values:

```text
scheduled
cancelled
postponed
happened
expired
```

Indexes:

```text
idx_catalyst_events_event_date (event_date)
idx_catalyst_events_status (status)
idx_catalyst_events_source (source_type, source_id)
idx_catalyst_events_subjects_gin GIN(subjects)
```

Stable ID:

```text
event_id = "CAT:" + sha256(source_type|source_id_or_title|event_date)[:20]
```

### 5.2 `signals` extension

Extend the existing `signals` table:

```text
signal_kind VARCHAR(24) NOT NULL DEFAULT 'observed'
event_date DATE
```

Allowed `signal_kind` values:

```text
observed
catalyst
```

`event_date` is required for `catalyst` signals and nullable for `observed` signals.

Add indexes:

```text
idx_signals_kind_value (signal_kind, value_score DESC, published_at DESC)
idx_signals_event_date (event_date)
```

P0 keeps catalyst-specific fields in `signals.metadata`:

```json
{
  "catalyst": {
    "event_id": "CAT:xxx",
    "lead_days": 5,
    "event_type": "conference",
    "alert_level": "high",
    "impact_scope": ["portfolio", "watchlist", "market"],
    "subjects": ["AI算力", "光模块", "CPO"],
    "possible_impact": "海外 AI 算力大会可能影响光模块/CPO 链预期"
  },
  "user_hits": {
    "portfolio": ["中际旭创", "新易盛"],
    "watchlist": [],
    "preferences": ["光模块", "CPO"]
  },
  "path_nodes": ["英伟达GTC", "AI算力", "光模块", "中际旭创"],
  "lifecycle": "upcoming"
}
```

### 5.3 Relationship to Observation -> Signal redesign

The existing codebase still uses the single-layer `signals` implementation. A later Observation -> Signal migration can preserve this design by treating `CatalystEvent` as the event fact source and `catalyst` as one signal kind in the aggregate signal layer.

Do not model future events as observations. A future scheduled event is not an observed market or text signal.

## 6. DTO and API

### 6.1 Signal list

Extend signal list items with:

```text
signal_kind
event_date
lead_days
alert_level
impact_scope
```

Supported query parameters:

```text
GET /api/signals?signal_kind=catalyst
GET /api/signals?window_days=5
GET /api/signals?include_kinds=observed,catalyst
```

Rules:

- `signal_kind` filters to one kind.
- `include_kinds` supports mixed dashboards.
- `window_days` applies to `catalyst.event_date` and defaults to five days when querying catalyst-only lists.
- Existing callers with no parameters continue to receive observed signals and any catalyst signals chosen by the service's default mixed-list policy.

### 6.2 Signal detail

Extend `SignalDetail` with:

```text
signal_kind
event_date
catalyst
```

Example:

```json
{
  "schema_version": "signal.context.v1",
  "signal_kind": "catalyst",
  "signal_id": "SIG:abc",
  "title": "未来5天英伟达GTC可能影响AI算力链",
  "summary": "英伟达开发者大会可能带来GPU、AI算力、光模块和CPO链关注度提升。",
  "event_date": "2026-07-28",
  "catalyst": {
    "event_id": "CAT:xxx",
    "event_type": "conference",
    "lead_days": 5,
    "alert_level": "high",
    "subjects": ["AI算力", "光模块", "CPO"],
    "impact_scope": ["portfolio", "market"]
  },
  "user_hits": {
    "portfolio": ["中际旭创", "新易盛"],
    "watchlist": [],
    "preferences": ["光模块", "CPO"]
  },
  "propagations": []
}
```

## 7. Generation Flow

### 7.1 Provider

Define a provider interface that returns catalyst event candidates. P0 includes:

- `FixtureCatalystProvider`: deterministic local fixtures.
- `CalendarCatalystProvider` interface only: no external implementation required.

Provider candidates include:

```text
event_type
title
event_date
event_time
timezone
source_type
source_id
source_url
importance
subjects
metadata
```

### 7.2 Upsert event

The service upserts candidates into `catalyst_events`.

Deduplication:

- Prefer `(source_type, source_id)` when `source_id` exists.
- Fall back to normalized `(title, event_date)`.
- Re-running fixture ingestion must not duplicate events.

### 7.3 Window selection

P0 generates alerts for events whose `event_date` is from today through today + five calendar days, inclusive.

Cancelled, postponed, expired, and happened events do not generate new upcoming alerts. Existing alerts for those events are downgraded or expired by a later lifecycle task; P0 may simply exclude them from default lists.

### 7.4 Subject mapping

Mapping priority:

1. Use `CatalystEvent.subjects`.
2. Map subject aliases to known KG names.
3. If no KG hit exists, still create a market-level catalyst signal with no propagation path.

### 7.5 Propagation

For each mapped subject, use existing KG propagation/path utilities where available.

P0 target depth:

```text
event subject -> concept/sector -> company
```

Each path produces a `SignalPropagation` when there is a meaningful target. The `relation_path` is human-readable, and `metadata.path_nodes` stores the node chain.

Confidence:

```text
path_confidence =
  event_importance / 100
  * relation_weight
  * hop_decay
```

Suggested defaults:

```text
relation_weight = 0.9 when KG path exists, 0.6 for alias-only mapping
hop_decay = 1.0 for 1-hop, 0.8 for 2-hop, 0.65 for 3-hop
```

### 7.6 User hit matching

Match against:

- account portfolio
- watchlist if available
- user memory preferences

P0 must work when watchlist or preferences are empty.

The matcher writes:

```text
metadata.user_hits.portfolio
metadata.user_hits.watchlist
metadata.user_hits.preferences
```

### 7.7 Signal generation

Signal ID:

```text
signal_id = "SIG:" + sha256("catalyst"|event_id|subject_or_path_hash)[:20]
```

Source fields:

```text
source_type = "catalyst_event"
source_id = event_id
source_title = catalyst_event.title
source_url = catalyst_event.source_url
published_at = null
event_date = catalyst_event.event_date
subject_name = primary subject
subject_type = concept / sector / company / macro / event
signal_type = event_type
polarity = neutral
strength = importance
confidence = path_confidence or 0.6 without KG path
freshness_score = future-window score
summary = possible impact summary
status = new
signal_kind = catalyst
```

Repeated generation updates existing catalyst signals:

- `event_date`
- `freshness_score`
- `value_score`
- `confidence`
- `metadata.catalyst.lead_days`
- `metadata.catalyst.alert_level`
- `metadata.user_hits`
- `updated_at`

## 8. Scoring

P0 uses transparent rule scoring:

```text
value_score =
  importance * 0.45
  + path_confidence * 100 * 0.25
  + user_hit_boost
  + freshness_window_score
```

User hit boosts:

```text
portfolio hit: +20
watchlist hit: +12
preference hit: +8
```

Freshness window score:

```text
today: +15
1-2 days: +12
3-5 days: +8
outside window: 0
```

Clamp `value_score` to `0..100`.

Alert level:

```text
high:
  value_score >= 80
  OR portfolio hit and importance >= 75

medium:
  value_score >= 60

low:
  otherwise
```

## 9. AgentContext

`format_signal_context` must branch by `signal_kind`.

For `catalyst` signals, format:

```text
<signal-context>
[未来催化预警]
- 未来5天英伟达GTC可能影响AI算力链
  signal_id: SIG:abc
  event_date: 2026-07-28, lead_days: 5, alert_level: high
  影响主题: AI算力、光模块、CPO
  相关持仓: 中际旭创、新易盛
  KG路径: 英伟达GTC -> AI算力 -> 光模块 -> 中际旭创
</signal-context>
```

The wording must make clear this is a future potential catalyst, not evidence that the market impact has already occurred.

## 10. Frontend

`SignalRadar` adds a simple kind filter:

```text
全部 / 已发生 / 未来预警
```

Catalyst cards show:

```text
[未来预警] 5天后
英伟达GTC可能影响AI算力链
命中：中际旭创、新易盛
路径：GTC -> AI算力 -> 光模块
```

Rules:

- Reuse the existing signal card and detail behavior.
- Do not create a separate Catalyst page in P0.
- Keep click-through behavior identical to observed signals.
- Use `alert_level` for visual priority, not investment language.

## 11. Testing Requirements

Backend tests:

- Fixture provider produces deterministic event candidates.
- Catalyst event upsert is idempotent.
- Five-day window filtering includes today and day five, excludes day six.
- Catalyst signal generation is idempotent for the same event/path.
- User portfolio hits write `metadata.user_hits.portfolio` and raise alert level when thresholds match.
- API list can filter `signal_kind=catalyst`.
- API list can filter by `window_days`.
- Detail DTO includes `signal_kind`, `event_date`, and `catalyst`.
- AgentContext formats `[未来催化预警]`.

Frontend tests:

- SignalRadar can display catalyst cards.
- Kind filter switches between all, observed, and catalyst.
- Catalyst cards show lead days and hit objects.

## 12. P0 Acceptance Criteria

- A local fixture event within the next five days generates one or more `catalyst` signals.
- Re-running generation does not duplicate events or signals.
- SignalRadar can show future alerts separately from observed signals.
- Clicking a catalyst signal returns detail with catalyst metadata, user hits, and propagation paths when available.
- AgentContext includes a future-catalyst-specific context block when invoked with a catalyst `signal_id`.
- The feature works without external API keys.
