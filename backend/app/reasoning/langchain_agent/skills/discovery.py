"""Skill 发现模块 — 扫描内置 + 外部目录，解析 frontmatter，缓存索引。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.reasoning.langchain_agent.skills.models import Skill, SkillIndex, _split_frontmatter

logger = logging.getLogger(__name__)

# 内置 skills 目录（相对于 reasoning 包）
_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"

# 外部 skills 目录（agent 创建）
_EXTERNAL_SKILLS_DIR = Path.home() / ".qingshui" / "skills"

# 排除的目录名
_EXCLUDED_DIRS = frozenset(
    {".git", "__pycache__", "node_modules", ".venv", "venv"}
)

# 内存缓存
_cache: dict[str, Skill] | None = None


def _get_skills_dirs() -> list[tuple[Path, bool]]:
    """返回 [(目录路径, is_builtin), ...] 列表。"""
    dirs: list[tuple[Path, bool]] = []
    if _BUILTIN_SKILLS_DIR.is_dir():
        dirs.append((_BUILTIN_SKILLS_DIR, True))
    if _EXTERNAL_SKILLS_DIR.is_dir():
        dirs.append((_EXTERNAL_SKILLS_DIR, False))
    return dirs


def _scan_dir(root: Path, is_builtin: bool) -> dict[str, Skill]:
    """扫描单个目录，返回 {name: Skill} 字典。"""
    skills: dict[str, Skill] = {}
    if not root.is_dir():
        return skills

    for skill_md in root.rglob("SKILL.md"):
        # 跳过排除目录
        parts = set(skill_md.parts)
        if parts & _EXCLUDED_DIRS:
            continue

        try:
            raw = skill_md.read_text(encoding="utf-8")
            frontmatter, _body = _split_frontmatter(raw)
        except Exception as e:
            logger.warning(f"Failed to read SKILL.md at {skill_md}: {e}")
            continue

        name = frontmatter.get("name", skill_md.parent.name)
        description = frontmatter.get("description", "")

        if not name or not description:
            logger.warning(f"Skipping skill at {skill_md}: missing name or description")
            continue

        skills[name] = Skill(
            name=name,
            description=description,
            path=skill_md,
            frontmatter=frontmatter,
            is_builtin=is_builtin,
        )

    return skills


def scan_skills(force: bool = False) -> dict[str, Skill]:
    """扫描所有 skill 目录，返回 {name: Skill} 字典。

    外部同名 skill 覆盖内置（外部优先）。
    结果缓存在内存中，除非 force=True。
    """
    global _cache

    if _cache is not None and not force:
        return _cache

    all_skills: dict[str, Skill] = {}

    for skills_dir, is_builtin in _get_skills_dirs():
        dir_skills = _scan_dir(skills_dir, is_builtin)
        # 外部覆盖内置（后扫描的覆盖先扫描的）
        all_skills.update(dir_skills)

    _cache = all_skills
    logger.info(f"Scanned {len(all_skills)} skills (builtin={sum(1 for s in all_skills.values() if s.is_builtin)})")
    return _cache


def get_skills_index() -> list[SkillIndex]:
    """返回轻量索引列表，用于注入 system prompt。"""
    skills = scan_skills()
    return [
        SkillIndex(
            name=s.name,
            description=s.description,
            related_skills=s.related_skills,
        )
        for s in skills.values()
    ]


def load_skill(name: str) -> Skill | None:
    """按名称加载完整 skill（含正文内容）。

    外部优先，其次内置。
    """
    skills = scan_skills()
    skill = skills.get(name)
    if skill is None:
        return None
    # 触发懒加载
    _ = skill.content
    return skill


def invalidate_cache() -> None:
    """清除缓存（skill_manage 修改后调用）。"""
    global _cache
    _cache = None


def _is_ascii(text: str) -> bool:
    """检查字符串是否只包含 ASCII 字符。"""
    return all(ord(c) < 128 for c in text)


def recommend_skills(query: str, top_k: int = 3) -> list[SkillIndex]:
    """根据用户查询推荐最相关的 skill。

    排序策略（简单加权）：
    1. 名称精确匹配 → 最高权重
    2. description 包含关键词
    3. tags 包含关键词
    4. related_skills 包含其他 skill 名

    Args:
        query: 用户查询文本
        top_k: 返回数量（默认 3）

    Returns:
        排序后的 SkillIndex 列表
    """
    skills = scan_skills()
    if not skills:
        return []

    query_lower = query.lower()
    # 中文：使用 2-char n-gram 匹配；英文/混合：使用分词匹配
    # 如果查询包含 ASCII 字母，只用完整查询 + 分词匹配
    use_ngrams = not _is_ascii(query_lower)
    if use_ngrams:
        query_words: set[str] = set()
        ngrams: set[str] = set(query_lower[i:i+2] for i in range(len(query_lower) - 1))
    else:
        query_words = set(query_lower.split())
        ngrams = set()

    scored: list[tuple[float, SkillIndex]] = []

    for skill in skills.values():
        score = 0.0

        # 名称精确/前缀匹配
        name_lower = skill.name.lower()
        if name_lower == query_lower:
            score += 100.0
        elif name_lower.startswith(query_lower):
            score += 50.0
        elif query_lower in name_lower:
            score += 20.0

        # description 关键词匹配
        desc_lower = skill.description.lower()
        if query_lower in desc_lower:
            score += 10.0
        if use_ngrams:
            for ngram in ngrams:
                if ngram in desc_lower:
                    score += 2.0
        for word in query_words:
            if word in desc_lower:
                score += 5.0

        # tags 匹配
        for tag in skill.tags:
            tag_lower = tag.lower()
            if tag_lower == query_lower:
                score += 30.0
            elif query_lower in tag_lower:
                score += 15.0
            if use_ngrams:
                for ngram in ngrams:
                    if ngram in tag_lower:
                        score += 3.0
            for word in query_words:
                if word in tag_lower:
                    score += 5.0

        # related_skills 匹配（query 可能是另一个 skill 名）
        for related in skill.related_skills:
            related_lower = related.lower()
            if query_lower in related_lower or related_lower in query_lower:
                score += 8.0

        if score > 0:
            scored.append((score, SkillIndex(
                name=skill.name,
                description=skill.description,
                related_skills=skill.related_skills,
            )))

    # 降序排序
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:top_k]]
