from app.reasoning.context.schemas import AgentContextDTO, SignalMemoryDTO, UserSnapshotDTO


def test_user_snapshot_defaults_are_empty_lists():
    dto = UserSnapshotDTO(user_id="lwm")

    assert dto.schema_version == "user.snapshot.v1"
    assert dto.portfolio == []
    assert dto.watchlist == []
    assert dto.preferences == []


def test_signal_memory_defaults_are_stable():
    dto = SignalMemoryDTO(signal_id="SIG:abc")

    assert dto.schema_version == "signal.memory.v1"
    assert dto.lifecycle_status == "active"
    assert dto.user_status == "new"
    assert dto.reinforced_count == 0
    assert dto.source_count == 1


def test_agent_context_defaults_include_warnings():
    dto = AgentContextDTO(
        context_type="signal_research",
        route="relation_reasoning",
        user_id="lwm",
        thread_id="t1",
        question="q",
    )

    assert dto.schema_version == "agent.context.v1"
    assert dto.warnings == []
    assert dto.prompt_context == ""
