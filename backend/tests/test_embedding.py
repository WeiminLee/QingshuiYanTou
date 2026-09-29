"""Phase 06 embedding/RAG integration tests."""

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestBatchReindexScheduler:
    """batch reindex 目前未注册：reindex_missing_vectors 尚未实现，注册会误报假成功。"""

    def test_batch_reindex_job_not_registered(self):
        from app.data_pipeline import scheduler as sched

        scheduler = sched.Scheduler()

        with patch.object(sched.AsyncIOScheduler, "start", return_value=None):
            scheduler.start()

        # 未实现前不应注册该任务，避免每晚假成功通知（详见 scheduler.start / vector_ops）
        job = scheduler._scheduler.get_job("batch_reindex_daily")
        assert job is None

    def test_run_now_does_not_dispatch_batch_reindex(self):
        from app.data_pipeline import scheduler as sched

        source = inspect.getsource(sched.Scheduler._fire_all_once)

        assert "_run_batch_reindex_job" not in source
        assert "batch_reindex_startup" not in source
