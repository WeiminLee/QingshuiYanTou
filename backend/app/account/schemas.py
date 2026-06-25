"""Pydantic 请求/响应模型"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


_TS_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    ok: bool = True
    users: List["UserBrief"] = Field(default_factory=list)


class SwitchUserRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)


class UserBrief(BaseModel):
    user_id: str
    display_name: str

    class Config:
        from_attributes = True


class UserBriefList(BaseModel):
    users: List[UserBrief]


class WhoAmIResponse(BaseModel):
    user: Optional[UserBrief] = None
    users: List[UserBrief] = Field(default_factory=list)


class SwitchUserResponse(BaseModel):
    ok: bool = True
    current_user: UserBrief


class PortfolioPositionOut(BaseModel):
    ts_code: str
    stock_name: str
    created_at: datetime

    class Config:
        from_attributes = True


class PortfolioListResponse(BaseModel):
    positions: List[PortfolioPositionOut]


class PortfolioAddRequest(BaseModel):
    ts_code: str = Field(min_length=1, max_length=16)

    @field_validator("ts_code")
    @classmethod
    def _check_ts_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not _TS_CODE_RE.match(v):
            raise ValueError("ts_code 格式应为 6 位数字+.SH/.SZ/.BJ")
        return v


class PortfolioAddResponse(BaseModel):
    ok: bool = True
    position: PortfolioPositionOut


class StockSearchItem(BaseModel):
    ts_code: str
    name: str
    industry: Optional[str] = None


class StockSearchResponse(BaseModel):
    items: List[StockSearchItem]


class OkResponse(BaseModel):
    ok: bool = True


LoginResponse.model_rebuild()
