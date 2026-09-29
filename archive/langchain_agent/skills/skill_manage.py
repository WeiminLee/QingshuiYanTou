"""Skill 管理工具 — write_skill（agent 自我进化接口）。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.reasoning.langchain_agent.skills.discovery import invalidate_cache

logger = logging.getLogger(__name__)

# 外部 skills 目录
_EXTERNAL_SKILLS_DIR = Path.home() / ".qingshui" / "skills"


class WriteSkillInput(BaseModel):
    """write_skill 的输入参数。"""
    name: str = Field(description="skill 名称（英文，kebab-case，如 my-custom-skill）")
    description: str = Field(description="简短描述，一句话说明用途")
    content: str = Field(description="skill 完整内容（Markdown 格式）")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    category: str = Field(default="custom", description="分类：finance/research/custom")
    related_skills: list[str] = Field(default_factory=list, description="关联的 skill 名称")


class WriteSkillTool(BaseTool):
    name: str = "write_skill"
    description: str = (
        "创建或更新一个 skill 文件。Agent 可用此工具将分析经验固化为可复用 skill，"
        "实现自我进化。仅写入外部 skills 目录（~/.qingshui/skills/），不影响内置 skill。"
    )
    args_schema: type[BaseModel] = WriteSkillInput

    def _run(
        self,
        name: str,
        description: str,
        content: str,
        tags: list[str],
        category: str,
        related_skills: list[str],
        **kwargs: Any,
    ) -> str:
        try:
            return self._write(name, description, content, tags, category, related_skills)
        except Exception as e:
            logger.exception(f"write_skill failed: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    def _write(
        self,
        name: str,
        description: str,
        content: str,
        tags: list[str],
        category: str,
        related_skills: list[str],
    ) -> str:
        # 验证 name 格式
        if not re.match(r"^[a-z0-9][-a-z0-9]*$", name):
            return json.dumps(
                {
                    "success": False,
                    "error": (
                        f"Invalid name '{name}': must be kebab-case (lowercase, numbers, hyphens only)"
                    ),
                },
                ensure_ascii=False,
            )

        # 构建 frontmatter
        frontmatter = {
            "name": name,
            "description": description,
            "version": "1.0.0",
            "metadata": {
                "tags": tags or [],
                "category": category,
                "related_skills": related_skills or [],
            },
        }

        # 序列化为 YAML frontmatter
        fm_yaml = yaml.safe_dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)
        raw = f"---\n{fm_yaml}---\n{content}"

        # 确保目录存在
        skill_dir = _EXTERNAL_SKILLS_DIR / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"

        # 写入文件
        skill_path.write_text(raw, encoding="utf-8")

        # 清除 discovery 缓存
        invalidate_cache()

        logger.info(f"write_skill: created/updated {skill_path}")
        return json.dumps(
            {
                "success": True,
                "message": f"Skill '{name}' 已保存到 {skill_path}",
                "path": str(skill_path),
                "name": name,
            },
            ensure_ascii=False,
        )
