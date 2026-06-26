"""Phase 06 embedding/RAG integration tests."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_pre_search_formats_all_hybrid_collections():
    """Agent pre-search should expose entity, relation, chunk, and QA results."""
    from app.knowledge.vector_client import SearchResult
    from app.reasoning.langchain_agent.client import _pre_search

    async def fake_hybrid_vector_search(**kwargs):
        assert kwargs == {
            "query": "光模块产业链",
            "top_k_per_collection": 5,
            "global_top_k": 4,
        }
        return [
            SearchResult(
                id="entity-1",
                score=0.4,
                payload={
                    "entity_id": "E1",
                    "entity_name": "中际旭创",
                    "description": "光模块龙头公司",
                    "ts_code": "300308.SZ",
                },
            ),
            SearchResult(
                id="relation-1",
                score=0.3,
                payload={
                    "from_name": "中际旭创",
                    "to_name": "英伟达",
                    "description": "向海外 AI 客户供应高速光模块",
                    "ts_code": "300308.SZ",
                },
            ),
            SearchResult(
                id="chunk-1",
                score=0.2,
                payload={
                    "content": "公司公告披露 800G 光模块收入增长。",
                    "heading": "年度报告",
                    "source": "annual-report",
                    "ts_code": "300308.SZ",
                },
            ),
            SearchResult(
                id="qa-1",
                score=0.1,
                payload={
                    "question": "光模块需求来自哪里？",
                    "answer": "AI 数据中心资本开支拉动。",
                    "source": "qa_flash",
                },
            ),
        ]

    with patch(
        "app.knowledge.vector_ops.hybrid_vector_search",
        new=fake_hybrid_vector_search,
    ):
        background = asyncio.run(_pre_search("光模块产业链", top_k=4))

    assert background.startswith("<background>\n## 相关背景知识\n")
    assert background.endswith("\n</background>")
    assert "[实体:中际旭创]" in background
    assert "[关系:中际旭创->英伟达]" in background
    assert "[文档:年度报告]" in background
    assert "[问答:光模块需求来自哪里？]" in background
    assert "AI 数据中心资本开支拉动" in background


class TestBatchReindexScheduler:
    """D-07 batch reindex is scheduled nightly, not dispatched at startup."""

    def test_batch_reindex_job_registered_at_0300(self):
        from app.data_pipeline import scheduler as sched

        scheduler = sched.Scheduler()

        with patch.object(sched.AsyncIOScheduler, "start", return_value=None):
            scheduler.start()

        job = scheduler._scheduler.get_job("batch_reindex_daily")
        assert job is not None

        trigger_text = str(job.trigger)
        assert f"hour='{sched.BATCH_REINDEX_HOUR}'" in trigger_text
        assert f"minute='{sched.BATCH_REINDEX_MINUTE}'" in trigger_text
        assert str(job.trigger.timezone) == sched.TIMEZONE

    def test_run_now_does_not_dispatch_batch_reindex(self):
        import inspect

        from app.data_pipeline import scheduler as sched

        source = inspect.getsource(sched.Scheduler._fire_all_once)

        assert "_run_batch_reindex_job" not in source
        assert "batch_reindex_startup" not in source
