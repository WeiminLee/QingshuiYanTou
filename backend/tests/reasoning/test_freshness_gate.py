from datetime import UTC, datetime

import pytest

from app.readiness.schemas import ReadinessSource, ReadinessSummary, SourceStatus, ThresholdKind
from app.reasoning.langchain_agent.freshness import (
    build_unavailable_freshness_context,
    load_freshness_context,
)


class FakeService:
    async def get_all(self):
        return ReadinessSummary(
            as_of=datetime(2026, 7, 21, 9, 0, tzinfo=UTC).isoformat(),
            overall_status="degraded",
            summary="1 个关键数据源已滞后，Agent 结论需要声明数据截至日期。",
            sources=[
                ReadinessSource(
                    source="announcement",
                    display_name="Announcements",
                    status=SourceStatus.STALE,
                    latest_data_date="2026-07-19",
                    latest_success_at=None,
                    lag_days=2,
                    threshold_days=1,
                    threshold_kind=ThresholdKind.NATURAL_DAY,
                    recommendation="数据已滞后 2 天，回答需要声明基于截至 2026-07-19 的数据。",
                )
            ],
        )


@pytest.mark.asyncio
async def test_load_freshness_context_formats_summary():
    text = await load_freshness_context(service=FakeService())

    assert "<data_readiness>" in text
    assert "overall_status=degraded" in text
    assert "announcement: stale" in text
    assert "不得输出强结论" not in text


def test_build_unavailable_freshness_context_truncates_error():
    text = build_unavailable_freshness_context("x" * 500)

    assert "overall_status=unavailable" in text
    assert "readiness_error=" in text
    assert len(text) < 700


def test_prompt_template_includes_freshness_context():
    from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template

    prompt = apply_prompt_template(
        background_context="",
        graph_context="",
        signal_context="",
        freshness_context="<data_readiness>\noverall_status=degraded\n</data_readiness>",
    )

    assert "<data_readiness>" in prompt
    assert "overall_status=degraded" in prompt
    assert "数据新鲜度" in prompt
