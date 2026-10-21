from app.signals.event_ingestion import event_to_source_payload
from app.signals.event_sources import resolve_event_origin, signal_source_type_for_origin


def test_event_family_maps_onto_a_signal_desk():
    cases = [
        ("announcement", "announcement", "announcement"),
        ("公告", "announcement", "announcement"),
        ("irm", "irm", "event"),
        ("互动易", "irm", "event"),
        ("cls", "cls", "news"),
        ("财联社", "cls", "news"),
        ("tushare", "cls", "news"),
        ("eastmoney_flash", "eastmoney", "news"),
        ("wallstreetcn", "news", "news"),
        ("ths", "news", "news"),
        ("sina", "news", "news"),
        ("pboc", "pboc", "event"),
        ("央行", "pboc", "event"),
        ("bloomberg", "bloomberg", "event"),
        ("彭博社", "bloomberg", "event"),
        ("some-wire", "news", "news"),
    ]
    for raw, origin, source_type in cases:
        assert resolve_event_origin(raw) == origin
        assert signal_source_type_for_origin(origin) == source_type


def test_dict_event_from_the_news_writer_is_accepted():
    payload = event_to_source_payload(
        {
            "event_id": "EV:1",
            "title": "标题",
            "summary": "摘要",
            "source": "tushare",
            "metadata": {"tags": ["算力概念"]},
        }
    )
    assert payload.source_type == "news"
    assert payload.metadata["event_origin"] == "cls"
    assert payload.metadata["tags"] == ["算力概念"]
