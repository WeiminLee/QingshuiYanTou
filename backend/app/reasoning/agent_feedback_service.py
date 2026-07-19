"""
agent_feedback_service — Agent 报告级反馈持久化。

区别于 knowledge/feedback_service（后者纠正 KG 关系 weight）：
这里记录用户对整篇 Agent 报告的点赞/点踩，写入 MongoDB agent_feedback collection，
供后续质量评估、prompt/工具调优离线分析使用。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

RATINGS = frozenset({"good", "bad"})


async def record_agent_feedback(
    task_id: str,
    rating: str,
    comment: str | None = None,
    question: str | None = None,
    user_id: str | None = None,
) -> dict:
    """记录一条报告级反馈。

    Args:
        task_id: 被评价的 Agent 任务 ID
        rating: "good" | "bad"
        comment: 可选文字补充
        question: 可选，冗余存原始问题便于离线分析
        user_id: 可选用户标识

    Returns:
        {"feedback_id", "task_id", "rating"}

    Raises:
        ValueError: rating 非法
    """
    if rating not in RATINGS:
        raise ValueError(f"无效 rating={rating}，有效值: {sorted(RATINGS)}")
    if not task_id:
        raise ValueError("task_id 不能为空")

    from app.core.mongodb import get_mongo_db

    feedback_id = str(uuid.uuid4())
    doc = {
        "_id": feedback_id,
        "task_id": task_id,
        "rating": rating,
        "comment": (comment or "").strip() or None,
        "question": question,
        "user_id": user_id or "anonymous",
        "timestamp": datetime.now(UTC),
    }

    db = get_mongo_db()
    await db.agent_feedback.insert_one(doc)
    logger.info(
        "Agent feedback recorded: task_id=%s rating=%s user=%s",
        task_id,
        rating,
        doc["user_id"],
    )

    return {"feedback_id": feedback_id, "task_id": task_id, "rating": rating}
