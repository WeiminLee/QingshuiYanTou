import inspect

from app.reasoning.langchain_agent import client as client_mod


def test_run_lead_agent_has_user_id_param():
    sig = inspect.signature(client_mod.run_lead_agent)
    assert "user_id" in sig.parameters


def test_client_uses_user_memory_provider_and_resolver():
    src = inspect.getsource(client_mod.run_lead_agent)
    assert "UserMemoryProvider" in src
    assert "resolve_user_id" in src
    # 不再用旧的 BuiltinProvider
    assert "BuiltinProvider" not in src
