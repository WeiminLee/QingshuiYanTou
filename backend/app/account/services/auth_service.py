"""认证服务：主密码校验 + master_token 签发/校验"""
from __future__ import annotations

import time
from typing import Optional

import jwt

import app.config as _cfg
from app.account import config as account_cfg


TOKEN_TYPE_MASTER = "master"


def _settings():
    return _cfg.settings


def verify_master_password(password: str) -> bool:
    """常数时间比较，避免计时攻击；不抛错"""
    if not password:
        return False
    expected = _settings().master_password or ""
    if not expected:
        return False
    import hmac
    return hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))


def issue_master_token() -> str:
    """签发一个 master token，过期时间 = 当前时间 + 50 年"""
    secret = account_cfg.derive_token_secret()
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 50 * 365 * 24 * 3600,
        "type": TOKEN_TYPE_MASTER,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_master_token(token: Optional[str]) -> bool:
    """校验 token：签名、过期、类型"""
    if not token:
        return False
    secret = account_cfg.derive_token_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return payload.get("type") == TOKEN_TYPE_MASTER
