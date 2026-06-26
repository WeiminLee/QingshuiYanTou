"""
知识构建层 — 分析师反馈 API

路由前缀：/api/v1/kg/feedback
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.knowledge.feedback_service import CORRECTION_TYPES, apply_feedback

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/kg/feedback", tags=["知识构建层"])


# ── Request / Response Models ───────────────────────────────────
class FeedbackRequest(BaseModel):
    relation_id: str
    type: str  # "confirm" | "reject" | "correct"
    corrected_weight: float | None = None  # required when type == "correct"
    user_id: str | None = None


class FeedbackResponse(BaseModel):
    relation_id: str
    previous_weight: float
    corrected_weight: float
    feedback_id: str


# ── 路由 ───────────────────────────────────────────────────────
@router.post("", response_model=FeedbackResponse)
async def submit_feedback(body: FeedbackRequest):
    """
    接收分析师纠错，更新 KG 关系 weight 并持久化记录。

    纠错类型：
    - confirm:  轻微提升 weight (+0.05，上限 1.0)
    - reject:   降低 weight (-0.15，下限 0.0)
    - correct:  设置为 corrected_weight（高置信关系有 floor 保护）

    weight 下限保护：当前 weight >= 0.85 的关系，corrected_weight 不得低于 0.50
    """
    if body.type not in CORRECTION_TYPES:
        raise HTTPException(status_code=400, detail=f"无效 type={body.type}，有效值: {sorted(CORRECTION_TYPES)}")

    try:
        result = await apply_feedback(
            rel_id=body.relation_id,
            correction_type=body.type,
            corrected_weight=body.corrected_weight,
            user_id=body.user_id,
        )
        return FeedbackResponse(**result)
    except ValueError as e:
        err_msg = str(e)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=404, detail=err_msg)
        raise HTTPException(status_code=400, detail=err_msg)
