"""/api/v1/auth/* 路由"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi import Cookie
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.deps import verify_master_token
from app.account.schemas import (
    LoginRequest,
    LoginResponse,
    OkResponse,
    SwitchUserRequest,
    SwitchUserResponse,
    UserBrief,
    WhoAmIResponse,
)
from app.account.services import auth_service, user_service
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["account"])


def _cookie_attrs() -> dict:
    """统一 cookie 属性：HttpOnly + Lax + （dev 下不必 Secure）"""
    return {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": False,
    }


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    if not auth_service.verify_master_password(req.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="主密码错误")
    token = auth_service.issue_master_token()
    response.set_cookie("master_token", token, **_cookie_attrs())
    users = await user_service.list_active(db)
    return LoginResponse(users=[UserBrief.model_validate(u) for u in users])


@router.post("/logout", response_model=OkResponse)
async def logout(response: Response, _=Depends(verify_master_token)) -> OkResponse:
    response.delete_cookie("master_token", path="/")
    response.delete_cookie("user_id", path="/")
    return OkResponse()


@router.post("/switch-user", response_model=SwitchUserResponse)
async def switch_user(
    req: SwitchUserRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_master_token),
) -> SwitchUserResponse:
    user = await user_service.get_active(db, req.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在或已停用")
    response.set_cookie("user_id", user.user_id, path="/", samesite="lax", secure=False)
    return SwitchUserResponse(current_user=UserBrief.model_validate(user))


@router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_master_token),
    user_id: str | None = Cookie(default=None),
) -> WhoAmIResponse:
    users = await user_service.list_active(db)
    briefs = [UserBrief.model_validate(u) for u in users]
    current: UserBrief | None = None
    if user_id:
        u = await user_service.get_active(db, user_id)
        if u is not None:
            current = UserBrief.model_validate(u)
    return WhoAmIResponse(user=current, users=briefs)
