import app.reasoning.langchain_agent.memory.user_resolver as ur


def test_explicit_user_id_returned():
    assert ur.resolve_user_id("lwm") == "lwm"


def test_whitespace_only_falls_back(monkeypatch):
    monkeypatch.setattr(ur, "_default_user_id", lambda: "fallback")
    assert ur.resolve_user_id("   ") == "fallback"


def test_none_falls_back(monkeypatch):
    monkeypatch.setattr(ur, "_default_user_id", lambda: "fallback")
    assert ur.resolve_user_id(None) == "fallback"


def test_default_user_id_hardcoded_when_no_users(monkeypatch):
    monkeypatch.setattr(ur, "_load_users", lambda: [])
    assert ur._default_user_id() == "default"


def test_default_user_id_takes_first(monkeypatch):
    class _U:
        def __init__(self, uid):
            self.user_id = uid

    monkeypatch.setattr(ur, "_load_users", lambda: [_U("alice"), _U("bob")])
    assert ur._default_user_id() == "alice"
