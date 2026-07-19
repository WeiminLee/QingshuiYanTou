from app.signals.context_provider import format_signal_context


def test_format_signal_context_includes_source_anchor_and_propagation():
    context = format_signal_context(
        {
            "signal_id": "SIG:abc",
            "title": "800G 光模块规模量产",
            "source_type": "announcement",
            "value_score": 92,
            "confidence": 0.92,
            "evidence_excerpt": "相关产品已进入规模量产阶段",
            "portfolio_hits": ["中际旭创", "新易盛"],
            "propagations": [
                {
                    "relation_path": "量产确认 -> 订单兑现概率提升 -> 供应链需求增强",
                    "reasoning": "高速光模块放量可能提升上游需求",
                }
            ],
        }
    )

    assert "<signal-context>" in context
    assert "800G 光模块规模量产" in context
    assert "相关产品已进入规模量产阶段" in context
    assert "中际旭创、新易盛" in context
    assert "量产确认 -> 订单兑现概率提升" in context
