from app.signals.context_provider import format_signal_context


def test_format_signal_context_for_catalyst_signal():
    text = format_signal_context(
        {
            "schema_version": "signal.context.v1",
            "signal_id": "SIG:cat",
            "signal_kind": "catalyst",
            "title": "未来5天英伟达GTC可能影响AI算力链",
            "value_score": 86,
            "confidence": 0.72,
            "source_type": "catalyst_event",
            "event_date": "2026-07-28",
            "catalyst": {
                "event_id": "CAT:abc",
                "event_type": "conference",
                "lead_days": 5,
                "alert_level": "high",
                "subjects": ["AI算力", "光模块", "CPO"],
                "impact_scope": ["portfolio", "market"],
            },
            "user_hits": {"portfolio": ["中际旭创"], "watchlist": [], "preferences": ["光模块"]},
            "propagations": [
                {
                    "relation_path": "英伟达GTC -> AI算力 -> 光模块 -> 中际旭创",
                    "reasoning": "未来大会可能提升相关主题关注度",
                    "signal_path": {"nodes": ["英伟达GTC", "AI算力", "光模块", "中际旭创"]},
                }
            ],
        }
    )

    assert "[未来催化预警]" in text
    assert "event_date: 2026-07-28, lead_days: 5, alert_level: high" in text
    assert "影响主题: AI算力、光模块、CPO" in text
    assert "相关持仓: 中际旭创" in text
    assert "KG路径: 英伟达GTC -> AI算力 -> 光模块 -> 中际旭创" in text
