from app.knowledge.evidence import JOB_STATUSES, STATUS_BLOCKED, STATUS_DEAD


def test_remote_worker_status_contract_includes_terminal_and_blocked_states():
    assert {STATUS_BLOCKED, STATUS_DEAD}.issubset(JOB_STATUSES)
