from __future__ import annotations

import logging
from typing import Any

from app.readiness.service import DataReadinessService, format_readiness_for_agent

logger = logging.getLogger(__name__)


def build_unavailable_freshness_context(error: str) -> str:
    short_error = (error or "unknown readiness error")[:300]
    return "\n".join(
        [
            "<data_readiness>",
            "overall_status=unavailable",
            f"readiness_error={short_error}",
            "answer_boundary=数据可用性检查失败，不得输出强时效结论；需要提示用户先确认同步状态。",
            "</data_readiness>",
        ]
    )


async def load_freshness_context(service: Any | None = None) -> str:
    active_service = service or DataReadinessService()
    try:
        summary = await active_service.get_all()
    except Exception as exc:
        logger.warning("[FreshnessGate] readiness lookup failed: %s", exc)
        return build_unavailable_freshness_context(str(exc))
    return format_readiness_for_agent(summary)
