# Divergence Knowledge HTTP tools — design note (2026-09-29 night)

**Decision:** Keep tool names `compare_metric` / `metric_trend` / `rollup_metric` / `fetch_evidence`.

**Why not rename:** Owner docs define 预期差 as **state evolution on a timeline** (not actual−consensus). The three metric tools already map cleanly to 横向 / 纵向 / 层次; renaming would burn Reviewer cycles without changing the contract.

**HTTP contracts** (X-API-Key, plugin never opens PG/Mongo/Qdrant):

| Tool | Method | Path | Body |
|---|---|---|---|
| compare_metric | POST | `/api/v1/knowledge/agent/compare_metric` | `{dimension, scope?, as_of?, top_k?}` |
| metric_trend | POST | `/api/v1/knowledge/agent/metric_trend` | `{subject, dimension?, limit?}` |
| rollup_metric | POST | `/api/v1/knowledge/agent/rollup_metric` | `{parent, scope?, top_k?}` |
| fetch_evidence | GET | `/api/v1/knowledge/evidence/{id}` | (existing) |
| semantic_search | POST | `/api/v1/knowledge/search/semantic` | optional cold-start |
| related_nodes / propagate_along | POST | `/api/v1/knowledge/agent/...` | 传导面 |

**Skill:** `plugins/qingshui/skills/divergence-mining` v3 — Evidence-first; judgments cite `EV:`; output structure locked to silicon-wafer v2 report sections.

**Retain:** Knowledge build / ingest / extract / scheduler / chemagent on FastAPI. Vue/LangChain not deleted tonight.
