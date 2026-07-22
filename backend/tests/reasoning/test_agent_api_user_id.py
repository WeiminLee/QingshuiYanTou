from app.reasoning.api import agent as agent_mod


def test_v2_chat_request_has_optional_user_id():
    fields = agent_mod.V2ChatRequest.model_fields
    assert "user_id" in fields
    # 默认可选
    assert fields["user_id"].is_required() is False


def test_v2_stream_request_has_optional_user_id():
    fields = agent_mod.V2StreamRequest.model_fields
    assert "user_id" in fields
    assert fields["user_id"].is_required() is False


def test_agent_request_user_id_prefers_explicit_value():
    assert agent_mod._resolve_request_user_id("body-user", "cookie-user") == "body-user"


def test_agent_request_user_id_falls_back_to_cookie():
    assert agent_mod._resolve_request_user_id(None, "cookie-user") == "cookie-user"


def test_agent_request_user_id_strips_blank_values():
    assert agent_mod._resolve_request_user_id("  ", " cookie-user ") == "cookie-user"
