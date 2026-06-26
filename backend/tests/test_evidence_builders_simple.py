"""Tests for evidence_builders_simple.py"""

from app.knowledge.evidence_builders_simple import (
    _file_exists,
    _map_file_path,
)


class TestPathMapping:
    """路径映射测试"""

    def test_map_old_path_to_new(self):
        """旧路径应映射到新路径"""
        old_path = "/home/lwm/qingshui_data/notices/000001.SZ/2024-01/test.pdf"
        result = _map_file_path(old_path)
        assert result == "/run/media/lwm/0E27099B0E27099B/qingshui_data/notices/000001.SZ/2024-01/test.pdf"

    def test_map_new_path_unchanged(self):
        """新路径保持不变"""
        new_path = "/run/media/lwm/0E27099B0E27099B/qingshui_data/notices/000001.SZ/2024-01/test.pdf"
        result = _map_file_path(new_path)
        assert result == new_path

    def test_map_none_returns_none(self):
        """None 输入返回 None"""
        assert _map_file_path(None) is None

    def test_file_exists_returns_false_for_none(self):
        """None 返回 False"""
        assert _file_exists(None) is False

    def test_map_empty_string_returns_none(self):
        """空字符串返回 None"""
        assert _map_file_path("") is None
