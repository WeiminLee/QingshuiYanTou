"""account 子包配置：读 users.yaml、派生 token 密钥、校验主密码"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

import app.config as _cfg


@dataclass(frozen=True)
class YamlUser:
    user_id: str
    display_name: str


def _settings():
    return _cfg.settings


def load_users_from_yaml(path: Path | None = None) -> list[YamlUser]:
    """读取 users.yaml，返回用户列表；文件不存在或解析失败抛错"""
    p = path or _settings().users_yaml_path
    if not p.exists():
        raise FileNotFoundError(f"users.yaml 不存在: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raw_users = data.get("users", [])
    if not isinstance(raw_users, list):
        raise ValueError("users.yaml 顶层 users 字段必须是列表")
    out: list[YamlUser] = []
    for item in raw_users:
        if not isinstance(item, dict):
            raise ValueError(f"users.yaml 条目必须是 dict: {item!r}")
        uid = str(item.get("user_id", "")).strip()
        name = str(item.get("display_name", "")).strip()
        if not uid or not name:
            raise ValueError(f"users.yaml 条目缺字段 user_id/display_name: {item!r}")
        out.append(YamlUser(user_id=uid, display_name=name))
    return out


def derive_token_secret() -> str:
    """从 MASTER_PASSWORD + 盐派生稳定的 token 签名密钥"""
    s = _settings()
    raw = f"{s.master_password}|{s.account_token_secret_salt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_master_password() -> None:
    """启动时调用：长度 < 8 抛 ValueError"""
    pw = _settings().master_password
    if not pw or len(pw) < 8:
        raise ValueError("MASTER_PASSWORD 未设置或长度 < 8（请在 backend/.env 配置）")
