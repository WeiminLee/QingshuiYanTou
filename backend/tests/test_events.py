import pytest

from app.data_pipeline.services.news_service import (
    auto_tag,
    stable_event_id,
)


class TestAutoTag:
    def test_match_single_concept(self):
        concepts = ["华为概念", "芯片概念", "5G概念"]
        tags = auto_tag("华为概念板块走强，AI芯片概念股活跃", concepts)
        assert "华为概念" in tags
        assert "芯片概念" in tags

    def test_no_match(self):
        concepts = ["锂电池概念", "新能源概念"]
        tags = auto_tag("华为AI芯片突破", concepts)
        assert tags == []

    def test_partial_match_not_counted(self):
        # "芯片" 不应匹配 "芯片概念" 如果概念名不完全出现
        concepts = ["芯片概念"]
        tags = auto_tag("芯片突破", concepts)
        assert tags == []


class TestStableEventId:
    def test_deterministic(self):
        title = "美国升级AI芯片出口管制"
        eid1 = stable_event_id(title)
        eid2 = stable_event_id(title)
        assert eid1 == eid2

    def test_different_titles_different_ids(self):
        eid1 = stable_event_id("新闻A")
        eid2 = stable_event_id("新闻B")
        assert eid1 != eid2
