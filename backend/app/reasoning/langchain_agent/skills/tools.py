"""Skill Agent Tools — skills_list + skill_view."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.reasoning.langchain_agent.skills.discovery import (
    get_skills_index,
    load_skill,
)

logger = logging.getLogger(__name__)

# ── skills_list ──────────────────────────────────────────────────────────


class SkillsListInput(BaseModel):
    """skills_list 的输入参数（无参数，列出所有 skill）。"""
    pass


class SkillsListTool(BaseTool):
    name: str = "skills_list"
    description: str = (
        "列出所有可用的 skill（name + description）。"
        "使用 skill_view(name) 加载完整内容。"
    )
    args_schema: type[BaseModel] = SkillsListInput

    def _run(self, **kwargs: Any) -> str:
        index = get_skills_index()
        if not index:
            return json.dumps(
                {"success": True, "skills": [], "count": 0, "message": "没有可用的 skill"},
                ensure_ascii=False,
            )

        skills_data = [
            {
                "name": s.name,
                "description": s.description,
                "related_skills": s.related_skills,
            }
            for s in index
        ]

        return json.dumps(
            {
                "success": True,
                "skills": skills_data,
                "count": len(skills_data),
                "hint": "使用 skill_view(name) 加载完整 skill 内容",
            },
            ensure_ascii=False,
        )


# ── skill_view ───────────────────────────────────────────────────────────


class SkillViewInput(BaseModel):
    """skill_view 的输入参数。"""
    name: str = Field(description="skill 名称（使用 skills_list 查看可用 skill）")


class SkillViewTool(BaseTool):
    name: str = "skill_view"
    description: str = (
        "加载指定 skill 的完整内容。"
        "Skill 包含详细的分析流程、工具组合和注意事项。"
        "当任务复杂时，优先加载对应 skill 获取指导。"
    )
    args_schema: type[BaseModel] = SkillViewInput

    def _run(self, name: str, **kwargs: Any) -> str:
        skill = load_skill(name)
        if skill is None:
            available = [s.name for s in get_skills_index()]
            return json.dumps(
                {
                    "success": False,
                    "error": f"Skill '{name}' 不存在",
                    "available_skills": available,
                    "hint": "使用 skills_list 查看所有可用 skill",
                },
                ensure_ascii=False,
            )

        result = {
            "success": True,
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "tags": skill.tags,
            "related_skills": skill.related_skills,
            "is_builtin": skill.is_builtin,
        }

        return json.dumps(result, ensure_ascii=False)


# ── 工具实例 ─────────────────────────────────────────────────────────────

skills_list_tool = SkillsListTool()
skill_view_tool = SkillViewTool()
