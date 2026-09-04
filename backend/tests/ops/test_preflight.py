from app.ops import preflight


def test_parse_target_accepts_database_urls():
    assert preflight.parse_target("mongo", "mongodb://10.20.0.1:27018/qingshui") == ("10.20.0.1", 27018)


def test_check_tcp_reports_connection_failure_without_raising():
    result = preflight.check_tcp("qdrant", "http://127.0.0.1:1", timeout=0.01)
    assert result.ok is False
    assert result.error
