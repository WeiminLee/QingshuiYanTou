"""Skill 数据模型 — 纯数据类，零外部依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    """单个 Skill 的完整表示。

    content 采用懒加载：创建实例时不读取文件正文，
    首次访问 .content 属性时才从磁盘读取。
    """

    name: str
    description: str
    path: Path  # SKILL.md 文件路径
    frontmatter: dict[str, Any] = field(default_factory=dict)
    is_builtin: bool = True
    _content: str | None = field(default=None, repr=False, init=False)

    @property
    def content(self) -> str:
        """懒加载：首次访问时从文件读取正文（不含 frontmatter）。"""
        if self._content is None:
            raw = self.path.read_text(encoding="utf-8")
            _, body = _split_frontmatter(raw)
            self._content = body
        return self._content

    @property
    def tags(self) -> list[str]:
        metadata = self.frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            return []
        tags = metadata.get("tags", [])
        if isinstance(tags, list):
            return [str(t) for t in tags]
        return []

    @property
    def related_skills(self) -> list[str]:
        metadata = self.frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            return []
        related = metadata.get("related_skills", [])
        if isinstance(related, list):
            return [str(r) for r in related]
        return []

    @property
    def category(self) -> str | None:
        metadata = self.frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            return None
        return metadata.get("category")


@dataclass
class SkillIndex:
    """注入 system prompt 的轻量索引 — 只含 name + description + 关联。"""

    name: str
    description: str
    related_skills: list[str] = field(default_factory=list)


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """解析 YAML frontmatter，返回 (frontmatter_dict, body)。"""
    import re

    import yaml

    frontmatter: dict[str, Any] = {}
    body = raw

    if not raw.startswith("---"):
        return frontmatter, body

    end_match = re.search(r"\n---\s*\n", raw[3:])
    if not end_match:
        return frontmatter, body

    yaml_content = raw[3 : end_match.start() + 3]
    body = raw[end_match.end() + 3 :]

    try:
        parsed = yaml.safe_load(yaml_content)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except Exception:
        pass

    return frontmatter, body