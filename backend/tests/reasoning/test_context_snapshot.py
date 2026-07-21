from app.reasoning.runtime.context_snapshot import build_context_snapshot


def test_build_context_snapshot_records_compression_and_structural_markers():
    snapshot = build_context_snapshot(
        before_messages=[
            {"role": "system", "content": "<data_readiness>\noverall_status=degraded\n</data_readiness>"},
            {"role": "user", "content": "<memory-context>偏好</memory-context>"},
            {"role": "tool", "content": "普通工具结果"},
        ],
        after_messages=[
            {"role": "system", "content": "<data_readiness>\noverall_status=degraded\n</data_readiness>"},
            {"role": "summary", "content": "[上下文压缩] 已略过 1 条中间消息"},
            {"role": "user", "content": "<memory-context>偏好</memory-context>"},
        ],
        before_tokens=1200,
        after_tokens=480,
        reason="threshold_exceeded",
        strategy="llm_summary",
    )

    data = snapshot.to_dict()

    assert data["compressed"] is True
    assert data["before_message_count"] == 3
    assert data["after_message_count"] == 3
    assert data["before_tokens"] == 1200
    assert data["after_tokens"] == 480
    assert data["tokens_saved"] == 720
    assert data["structural_markers"] == ["data_readiness", "memory_context"]
    assert data["preserved_markers"] == ["data_readiness", "memory_context"]
    assert data["lost_markers"] == []


def test_build_context_snapshot_marks_lost_structural_marker():
    snapshot = build_context_snapshot(
        before_messages=[{"role": "system", "content": "<graph_context>图谱</graph_context>"}],
        after_messages=[{"role": "summary", "content": "summary"}],
        before_tokens=100,
        after_tokens=20,
        reason="manual",
        strategy="truncate",
    )

    assert snapshot.to_dict()["lost_markers"] == ["graph_context"]
