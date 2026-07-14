"""Tests for agent_feedback_service + POST /api/v1/agent/feedback。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRecordAgentFeedback:
    def test_records_good_feedback(self):
        import asyncio

        from app.reasoning.agent_feedback_service import record_agent_feedback

        fake_db = MagicMock()
        fake_db.agent_feedback.insert_one = AsyncMock()

        with patch("app.core.mongodb.get_mongo_db", return_value=fake_db):
            out = asyncio.run(record_agent_feedback("task-1", "good", comment="很好"))

        assert out["task_id"] == "task-1"
        assert out["rating"] == "good"
        assert out["feedback_id"]
        # 校验落库文档
        fake_db.agent_feedback.insert_one.assert_awaited_once()
        doc = fake_db.agent_feedback.insert_one.await_args.args[0]
        assert doc["task_id"] == "task-1"
        assert doc["rating"] == "good"
        assert doc["comment"] == "很好"
        assert doc["user_id"] == "anonymous"
        assert "timestamp" in doc

    def test_blank_comment_stored_as_none(self):
        import asyncio

        from app.reasoning.agent_feedback_service import record_agent_feedback

        fake_db = MagicMock()
        fake_db.agent_feedback.insert_one = AsyncMock()

        with patch("app.core.mongodb.get_mongo_db", return_value=fake_db):
            asyncio.run(record_agent_feedback("task-2", "bad", comment="   ", user_id="u1"))

        doc = fake_db.agent_feedback.insert_one.await_args.args[0]
        assert doc["comment"] is None
        assert doc["user_id"] == "u1"

    def test_invalid_rating_raises(self):
        import asyncio

        from app.reasoning.agent_feedback_service import record_agent_feedback

        with pytest.raises(ValueError, match="无效 rating"):
            asyncio.run(record_agent_feedback("task-3", "meh"))

    def test_empty_task_id_raises(self):
        import asyncio

        from app.reasoning.agent_feedback_service import record_agent_feedback

        with pytest.raises(ValueError, match="task_id"):
            asyncio.run(record_agent_feedback("", "good"))


class TestFeedbackEndpoint:
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.reasoning.api import agent as agent_api

        app = FastAPI()
        app.include_router(agent_api.router, prefix="/api/v1/agent")
        # 绕过鉴权
        app.dependency_overrides[agent_api.verify_api_key] = lambda: None
        return TestClient(app)

    def test_post_feedback_ok(self):
        client = self._client()
        with patch(
            "app.reasoning.agent_feedback_service.record_agent_feedback",
            new=AsyncMock(return_value={"feedback_id": "fb-1", "task_id": "t1", "rating": "good"}),
        ):
            resp = client.post("/api/v1/agent/feedback", json={"task_id": "t1", "rating": "good"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["feedback_id"] == "fb-1"
        assert body["rating"] == "good"

    def test_post_feedback_invalid_rating_returns_400(self):
        client = self._client()
        resp = client.post("/api/v1/agent/feedback", json={"task_id": "t1", "rating": "nope"})
        assert resp.status_code == 400
