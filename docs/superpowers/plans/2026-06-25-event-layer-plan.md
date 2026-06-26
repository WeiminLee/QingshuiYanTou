# 事件层 Phase 1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现财联社新闻接入 + 存储 + Agent 事件搜索工具（Phase 1 + Phase 1.5 自动标签）

**Architecture:**
1. Tushare 财联社新闻定时同步 → PostgreSQL events 表（含自动标签）
2. Agent 工具 `find_events` / `get_event_detail` 提供事件搜索
3. Agent 推理时自主组合事件 + 概念/个股查询工具完成事件→个股映射

**Tech Stack:** Python, asyncio, Tushare, PostgreSQL (jsonb + GIN), APScheduler, LangChain @tool, Alembic

## 全局约束

- 事件不进 Neo4j、不预建事件→个股映射表、不预分类情感/类型
- Agent 工具使用 `@tool` 装饰器注册，通过 `config.yaml` 配置
- 使用项目已有的 `tushare_token` 和 `tushare_http_url` 配置项（`app/config.py:44-45`）
- 数据库迁移使用 Alembic（最新版本 `023`，基础 `down_revision = "023"`）

---

## 1. 文件变更概览

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/app/models/event.py` | 创建 | Event SQLAlchemy 模型 |
| `backend/alembic/versions/024_add_events_table.py` | 创建 | events 表 + 索引 |
| `backend/app/data_pipeline/services/news_service.py` | 创建 | Tushare 新闻拉取 + 去重 + 自动标签 + 入库 |
| `backend/app/data_pipeline/scheduler.py` | 修改 | 注册新闻同步定时任务 |
| `backend/app/reasoning/tools/market_data/events/__init__.py` | 创建 | 工具包入口 |
| `backend/app/reasoning/tools/market_data/events/events.py` | 创建 | `find_events` + `get_event_detail` 实现 |
| `backend/app/reasoning/registry/config.yaml` | 修改 | 注册两个新工具 |
| `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py` | 修改 | 加入事件搜索提示 |
| `backend/tests/test_events.py` | 创建 | NewsService + Agent 工具测试 |

---

## 2. 任务列表

### Task 1: 数据库模型 + 迁移

**文件:**
- Create: `backend/app/models/event.py`
- Create: `backend/alembic/versions/024_add_events_table.py`
- Test: 迁移执行验证

---

- [ ] **Step 1: 创建 Event SQLAlchemy 模型**

```python
# backend/app/models/event.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="cls")
    url: Mapped[str | None] = mapped_column(Text)
    publish_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )


Index("idx_events_publish_at", Event.publish_at, postgresql_using="btree")
Index("idx_events_source", Event.source, postgresql_using="btree")
Index("idx_events_tags", Event.metadata_, postgresql_using="gin", postgresql_ops={"metadata": "jsonb_path_ops"})
```

```python
# backend/app/models/__init__.py — 加入导出
# 在文件末尾添加:
from app.models.event import Event


# backend/alembic/env.py — 加入 Event 导入确保 Alembic 能发现该模型
# 在 line 15-18 的区域添加:
from app.models.event import Event  # noqa: E402, F401
```

---

- [ ] **Step 2: 创建 Alembic 迁移**

```python
# backend/alembic/versions/024_add_events_table.py
"""add events table (财联社新闻事件库)

Revision ID: 024
Revises: 023
Create Date: 2026-06-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "024"
down_revision: Union[str, Sequence[str], None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(32), unique=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="cls"),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("publish_at", postgresql.TIMESTAMPTZ(), nullable=False),
        sa.Column("ingested_at", postgresql.TIMESTAMPTZ(), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("idx_events_publish_at", "events", ["publish_at"])
    op.create_index("idx_events_source", "events", ["source"])
    op.create_index(
        "idx_events_tags", "events", ["metadata"],
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_events_tags", table_name="events")
    op.drop_index("idx_events_source", table_name="events")
    op.drop_index("idx_events_publish_at", table_name="events")
    op.drop_table("events")
```

---

- [ ] **Step 3: 验证迁移**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
alembic upgrade head
# 预期输出: INFO  [alembic.runtime.migration] Running upgrade 023 -> 024
```

```bash
# 验证表存在
python -c "
from app.core.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='events'\"))
    print([r[0] for r in result])
"
# 预期输出: ['id', 'event_id', 'title', 'summary', 'content', 'source', 'url', 'publish_at', 'ingested_at', 'metadata']
```

---

### Task 2: NewsService

**文件:**
- Create: `backend/app/data_pipeline/services/news_service.py`
- Test: `backend/tests/test_events.py`

**接口:**
- Produces: `NewsService.fetch_and_save() → dict` (拉取+去重+标签+入库)
- Produces: `auto_tag(title, concept_names) → list[str]`

---

- [ ] **Step 1: 编写测试**

```python
# backend/tests/test_events.py
import pytest
from datetime import datetime, timezone

from app.data_pipeline.services.news_service import (
    auto_tag,
    stable_event_id,
)


class TestAutoTag:
    def test_match_single_concept(self):
        concepts = ["华为概念", "芯片概念", "5G概念"]
        tags = auto_tag("华为AI芯片突破，昇腾910B性能提升300%", concepts)
        assert "华为概念" in tags
        assert "芯片概念" in tags

    def test_no_match(self):
        concepts = ["锂电池概念", "新能源概念"]
        tags = auto_tag("华为AI芯片突破", concepts)
        assert tags == []

    def test_partial_match_not_counted(self):
        # "芯片" 不应匹配 "芯片概念" 如果概念名不完全出现
        concepts = ["芯片概念"]
        tags = auto_tag("芯片突破", concepts)
        assert tags == []


class TestStableEventId:
    def test_deterministic(self):
        title = "美国升级AI芯片出口管制"
        eid1 = stable_event_id(title)
        eid2 = stable_event_id(title)
        assert eid1 == eid2

    def test_different_titles_different_ids(self):
        eid1 = stable_event_id("新闻A")
        eid2 = stable_event_id("新闻B")
        assert eid1 != eid2
```

---

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_events.py -v
# 预期: FAIL (ImportError — module not found)
```

---

- [ ] **Step 3: 编写 NewsService 实现**

```python
# backend/app/data_pipeline/services/news_service.py
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import tushare as ts

from app.config import settings
from app.core.database import engine
from app.models.event import Event

logger = logging.getLogger(__name__)

_TUSHARE_PRO: Any = None


def _get_ts_pro():
    global _TUSHARE_PRO
    if _TUSHARE_PRO is None:
        ts.set_token(settings.tushare_token)
        _TUSHARE_PRO = ts.pro_api()
    return _TUSHARE_PRO


def stable_event_id(title: str) -> str:
    raw = (title or "").strip()[:16]
    return f"EV:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def auto_tag(title: str, concept_names: list[str]) -> list[str]:
    tags = []
    for name in concept_names:
        if name in title:
            tags.append(name)
    return tags


class NewsService:
    def __init__(self):
        self._concept_names: list[str] | None = None

    async def _load_concept_names(self) -> list[str]:
        if self._concept_names is not None:
            return self._concept_names
        from app.models.models import ThsConcept
        from sqlalchemy import select
        async with engine.connect() as conn:
            result = await conn.execute(select(ThsConcept.name))
            names = [r[0] for r in result.fetchall()]
        self._concept_names = names
        return names

    async def fetch_and_save(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 200,
    ) -> dict[str, int]:
        pro = _get_ts_pro()
        src = settings.tushare_http_url.rstrip("/")
        try:
            df = pro.news(
                src=src,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            df = pro.major_news(
                src=src,
                start_date=start_date,
                end_date=end_date,
            )

        if df is None or df.empty:
            return {"fetched": 0, "inserted": 0, "skipped": 0}

        concept_names = await self._load_concept_names()
        inserted = 0
        skipped = 0

        async with engine.connect() as conn:
            for _, row in df.head(limit).iterrows():
                title = str(row.get("title") or "")
                if not title.strip():
                    skipped += 1
                    continue

                eid = stable_event_id(title)
                tags = auto_tag(title, concept_names)
                metadata = {"tags": tags} if tags else {}

                stmt = Event.__table__.insert().values(
                    event_id=eid,
                    title=title,
                    summary=str(row.get("content") or row.get("summary") or ""),
                    source="cls",
                    url=str(row.get("url") or ""),
                    publish_at=_parse_datetime(row.get("pub_time") or row.get("datetime") or ""),
                    metadata=metadata,
                ).prefix_with("INSERT INTO events", dialect="postgresql")
                # Using ON CONFLICT DO NOTHING
                from sqlalchemy import text

                pg_stmt = text("""
                    INSERT INTO events (event_id, title, summary, source, url, publish_at, metadata)
                    VALUES (:event_id, :title, :summary, :source, :url, :publish_at, :metadata::jsonb)
                    ON CONFLICT (event_id) DO NOTHING
                """)
                result = await conn.execute(pg_stmt, {
                    "event_id": eid,
                    "title": title,
                    "summary": str(row.get("content") or row.get("summary") or ""),
                    "source": "cls",
                    "url": str(row.get("url") or ""),
                    "publish_at": _parse_datetime(row.get("pub_time") or row.get("datetime") or ""),
                    "metadata": str(metadata).replace("'", '"'),
                })
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1

            await conn.commit()

        return {"fetched": len(df), "inserted": inserted, "skipped": skipped}


def _parse_datetime(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


_news_service: NewsService | None = None


def get_news_service() -> NewsService:
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service
```

---

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_events.py -v
# 预期: PASS
```

---

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/event.py backend/alembic/versions/024_add_events_table.py backend/app/data_pipeline/services/news_service.py backend/tests/test_events.py
git commit -m "feat: add events table + NewsService for 财联社 news sync"
```

---

### Task 3: 调度器注册

**文件:**
- Modify: `backend/app/data_pipeline/scheduler.py`

**接口:**
- Consumes: `NewsService.fetch_and_save()`

---

- [ ] **Step 1: 添加新闻同步任务**

在 `scheduler.py` 中添加新的任务函数和常量：

```python
# 在常量区域附近添加（约 line 53）:
NEWS_FETCH_MINUTE = "*/5"  # 每 5 分钟
NEWS_FETCH_HISTORY_DAYS = 7  # 首次全量拉取历史天数
```

```python
# 添加新的任务函数（在 _run_pdf_rotation_job 附近）:
async def _run_news_job() -> None:
    """财联社新闻定时同步（每 5 分钟）。"""
    from app.data_pipeline.services.news_service import get_news_service

    service = get_news_service()
    result = await service.fetch_and_save()
    logger.info("[news_sync] 同步结果: fetched=%d inserted=%d skipped=%d",
                result.get("fetched", 0), result.get("inserted", 0), result.get("skipped", 0))
```

---

- [ ] **Step 2: 注册到 start()**

```python
# 在 Scheduler.start() 中添加（在 self._scheduler.start() 之前任意位置）:
        self._scheduler.add_job(
            _run_news_job,
            CronTrigger(minute=NEWS_FETCH_MINUTE, timezone=TIMEZONE),
            id="news_sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
```

---

- [ ] **Step 3: 注册到 _fire_all_once()**

```python
# 在 _fire_all_once() 的 task_specs 列表中添加:
            (_run_news_job(), "news_startup"),
```

---

- [ ] **Step 4: 提交**

```bash
git add backend/app/data_pipeline/scheduler.py
git commit -m "feat: register news sync scheduler task"
```

---

### Task 4: Agent 工具

**文件:**
- Create: `backend/app/reasoning/tools/market_data/events/__init__.py`
- Create: `backend/app/reasoning/tools/market_data/events/events.py`
- Create: `backend/app/reasoning/tools/market_data/concept_stocks.py`（或扩展现有工具）
- Test: `backend/tests/test_events.py` 追加

**接口:**
- Produces: `find_events(query, tags, date_from, date_to, top_n) → str`
- Produces: `get_event_detail(event_id) → str`

---

- [ ] **Step 1: 编写工具测试**

```python
# 追加到 backend/tests/test_events.py

class TestFindEventsTool:
    @pytest.mark.asyncio
    async def test_format_output(self):
        from app.reasoning.tools.market_data.events.events import _format_event_list
        events = [
            {"event_id": "EV:abc", "title": "测试事件", "summary": "摘要", "source": "cls", "publish_at": "2026-06-25 08:30"},
        ]
        result = _format_event_list(events, "测试")
        assert "测试事件" in result


class TestEventDetailTool:
    @pytest.mark.asyncio
    async def test_format_detail(self):
        from app.reasoning.tools.market_data.events.events import _format_event_detail
        event = {
            "event_id": "EV:abc",
            "title": "测试事件",
            "content": "全文内容",
            "source": "cls",
            "publish_at": "2026-06-25 08:30",
        }
        result = _format_event_detail(event)
        assert "EV:abc" in result
        assert "全文内容" in result
```

---

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_events.py::TestFindEventsTool -v
# 预期: FAIL (import error)
```

---

- [ ] **Step 3: 编写工具实现**

```python
# backend/app/reasoning/tools/market_data/events/events.py
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool
from sqlalchemy import text

from app.core.database import engine
from app.reasoning.tools._async_runner import run_async

logger = logging.getLogger(__name__)


@tool("find_events")
def find_events(
    query: Annotated[str | None, "搜索关键词，越精确越好（如 'AI芯片 制裁 中际旭创'）。query 和 tags 可选至少传一个"] = None,
    tags: Annotated[list[str] | None, "板块/概念标签过滤（如 ['芯片概念', '华为概念']）。事件入库时会自动打标签，可用来精确筛选"] = None,
    date_from: Annotated[str | None, "开始日期 YYYYMMDD，不传则不限制"] = None,
    date_to: Annotated[str | None, "结束日期 YYYYMMDD，不传则到今天"] = None,
    top_n: Annotated[int, "返回条数，默认 10，最多 30"] = 10,
) -> str:
    """搜索财联社事件库。按关键词或板块标签查找相关事件，支持按时间范围过滤。
    适合用来查询最近影响某个行业、板块或个股的新闻事件。"""
    top_n = min(max(top_n, 1), 30)
    return run_async(_find_events(query, tags, date_from, date_to, top_n))


async def _find_events(
    query: str | None,
    tags: list[str] | None,
    date_from: str | None,
    date_to: str | None,
    top_n: int,
) -> str:
    if not query and not tags:
        return "请至少提供搜索关键词(query)或板块标签(tags)。"

    conditions: list[str] = []
    params: dict = {}

    # tags 过滤（使用 jsonb @> 操作符）
    if tags:
        tag_conditions = []
        for i, tag in enumerate(tags):
            key = f"tag_{i}"
            tag_conditions.append(f"metadata @> :{key}")
            params[key] = f'{{"tags": ["{tag}"]}}'
        conditions.append(f"({' OR '.join(tag_conditions)})")

    # query 关键词过滤
    if query:
        keywords = [kw.strip() for kw in query.split() if kw.strip()]
        kw_conditions = []
        for i, kw in enumerate(keywords):
            key = f"kw_{i}"
            kw_conditions.append(f"title ILIKE :{key}")
            params[key] = f"%{kw}%"
        conditions.append(f"({' AND '.join(kw_conditions)})")

    # 时间范围过滤
    if date_from:
        conditions.append("publish_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("publish_at <= :date_to")
        params["date_to"] = date_to

    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT event_id, title, summary, source, publish_at
        FROM events
        WHERE {where_clause}
        ORDER BY publish_at DESC
        LIMIT :top_n
    """
    params["top_n"] = top_n

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()

    if not rows:
        return "未找到匹配的事件。"

    events = [
        {
            "event_id": r[0],
            "title": r[1],
            "summary": (r[2] or "")[:200],
            "source": r[3],
            "publish_at": str(r[4]) if r[4] else "",
        }
        for r in rows
    ]
    return _format_event_list(events, query or "")


def _format_event_list(events: list[dict], query: str) -> str:
    lines = [f"## 事件搜索结果（关键词：{query or '全部'}）\n"]
    for i, ev in enumerate(events, 1):
        lines.append(f"**{i}.** {ev['title']}")
        lines.append(f"   📅 {ev['publish_at']}  |  来源：{ev['source']}")
        if ev['summary']:
            lines.append(f"   摘要：{ev['summary'][:150]}")
        lines.append(f"   ID: `{ev['event_id']}`")
        lines.append("")
    return "\n".join(lines)


@tool("get_event_detail")
def get_event_detail(
    event_id: Annotated[str, "事件 ID（EV: 开头）"],
) -> str:
    """获取事件的原始全文内容。在 find_events 找到感兴趣的事件后调用。"""
    return run_async(_get_event_detail(event_id))


async def _get_event_detail(event_id: str) -> str:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT event_id, title, content, source, publish_at FROM events WHERE event_id = :eid"),
            {"eid": event_id},
        )
        row = result.fetchone()

    if not row:
        return f"未找到事件: {event_id}"

    return _format_event_detail({
        "event_id": row[0],
        "title": row[1],
        "content": row[2] or "（无全文内容）",
        "source": row[3],
        "publish_at": str(row[4]) if row[4] else "",
    })


def _format_event_detail(event: dict) -> str:
    return (
        f"## 事件详情\n"
        f"ID: {event['event_id']}\n"
        f"标题: {event['title']}\n"
        f"时间: {event['publish_at']}\n"
        f"来源: {event['source']}\n\n"
        f"【全文内容】\n{event['content']}"
    )
```

```python
# backend/app/reasoning/tools/market_data/events/__init__.py
from app.reasoning.tools.market_data.events.events import find_events, get_event_detail

__all__ = ["find_events", "get_event_detail"]
```

---

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_events.py -v
# 预期: PASS
```

---

- [ ] **Step 5: 提交**

```bash
git add backend/app/reasoning/tools/market_data/events/
git commit -m "feat: add find_events and get_event_detail agent tools"
```

---

### Task 5: 工具注册 + System Prompt

**文件:**
- Modify: `backend/app/reasoning/registry/config.yaml`
- Modify: `backend/app/reasoning/registry/loader.py`（_build_default_config 同步）
- Modify: `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`

---

- [ ] **Step 1: 在 config.yaml 中注册两个新工具**

```yaml
  # ── events (财联社新闻) ──────────────────────────────────────────

  - name: find_events
    group: market_data
    use: app.reasoning.tools.market_data.events:find_events
    description: 搜索财联社事件库，按关键词或板块标签查找新闻事件，支持按时间范围过滤

  - name: get_event_detail
    group: market_data
    use: app.reasoning.tools.market_data.events:get_event_detail
    description: 获取事件原始全文内容。在 find_events 找到感兴趣的事件后调用
```

---

- [ ] **Step 2: 在 _build_default_config() 中同步添加**

```python
        # ── events ────────────────────────────────────
        ToolConfig(
            name="find_events",
            group=ToolGroup.MARKET_DATA,
            use="app.reasoning.tools.market_data.events:find_events",
            description="搜索财联社事件库，按关键词或板块标签查找新闻事件",
        ),
        ToolConfig(
            name="get_event_detail",
            group=ToolGroup.MARKET_DATA,
            use="app.reasoning.tools.market_data.events:get_event_detail",
            description="获取事件原始全文内容",
        ),
```

---

- [ ] **Step 3: 在系统提示中加入事件搜索策略**

在 `lead_system_prompt.py` 中场景化工具组合段落，对 `tavily_search` 出现的 3 个场景分别补充：

**场景 A（个股深度分析）— line 180**：`5. `tavily_search` → 实时新闻和政策动态` 改为：
```
   5. `find_events` + `tavily_search` → 实时新闻和政策动态（国内事件优先 find_events）
```

**场景 B（行业/板块扫描）— line 185**：`2. `tavily_search` → 行业动态和政策` 改为：
```
   2. `find_events` + `tavily_search` → 行业动态和政策
```

**场景 C（事件驱动分析）— line 189-190**：
```
场景 C — 事件驱动分析（新闻/公告触发）：
   1. `find_events` → 财联社事件搜索（查国内 A 股相关新闻）
   2. `get_event_detail` → 获取感兴趣事件的全文
   3. `tavily_search` + `web_fetch` → 补充外部视角
   4. `get_announcement` → 官方公告
   5. `resolve` → `expand(select=["relations"])` → 影响传导链
   6. `get_kline` → 价格反应验证
```

---

- [ ] **Step 4: 验证工具加载**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -c "
from app.reasoning.tools.tools import get_available_tools
tools = get_available_tools()
names = [t.name for t in tools]
assert 'find_events' in names, 'find_events not loaded'
assert 'get_event_detail' in names, 'get_event_detail not loaded'
print('✅ 工具注册验证通过')
"
```

---

- [ ] **Step 5: 提交**

```bash
git add backend/app/reasoning/registry/config.yaml backend/app/reasoning/registry/loader.py backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py
git commit -m "feat: register find_events/get_event_detail tools and update prompts"
```

---

### Task 6: 集成测试

**文件:**
- Modify: `backend/tests/test_events.py`

---

- [ ] **Step 1: 编写 NewsService 集成测试（mock tushare）**

```python
# 追加到 backend/tests/test_events.py

class TestNewsServiceIntegration:
    @pytest.mark.asyncio
    async def test_fetch_and_save_with_mock(self, mocker):
        import pandas as pd
        from app.data_pipeline.services.news_service import get_news_service

        # mock tushare pro.news()
        mock_df = pd.DataFrame([
            {"title": "测试新闻A", "content": "摘要A", "pub_time": "2026-06-25 08:30:00", "url": "http://example.com/a"},
            {"title": "测试新闻B：芯片概念", "content": "摘要B", "pub_time": "2026-06-25 09:00:00", "url": ""},
        ])
        mock_pro = mocker.MagicMock()
        mock_pro.news.return_value = mock_df

        mocker.patch("app.data_pipeline.services.news_service._get_ts_pro", return_value=mock_pro)
        mocker.patch.object(get_news_service(), "_load_concept_names", return_value=["芯片概念"])

        result = await get_news_service().fetch_and_save(limit=10)
        assert result["fetched"] == 2
```

---

- [ ] **Step 2: 运行集成测试**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_events.py -v
# 预期: ALL PASS
```

---

- [ ] **Step 3: 提交**

```bash
git add backend/tests/test_events.py
git commit -m "test: add integration tests for NewsService and event tools"
```

---

## 3. 验证清单

```bash
# 1. 迁移
alembic upgrade head

# 2. 测试
pytest tests/test_events.py -v

# 3. 工具加载
python -c "
from app.reasoning.tools.tools import get_available_tools
tools = get_available_tools()
names = [t.name for t in tools]
assert 'find_events' in names
assert 'get_event_detail' in names
print('✅ 全部就绪')
"

# 4. ruff 检查
ruff check app/data_pipeline/services/news_service.py app/reasoning/tools/market_data/events/
ruff format --check app/data_pipeline/services/news_service.py app/reasoning/tools/market_data/events/
```
