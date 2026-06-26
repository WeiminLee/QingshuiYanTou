"""/api/v1/portfolio 路由：持仓增删查"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.deps import get_current_user, verify_master_token
from app.account.schemas import (
    OkResponse,
    PortfolioAddRequest,
    PortfolioAddResponse,
    PortfolioListResponse,
    PortfolioPositionOut,
    StockSearchResponse,
)
from app.account.services import portfolio_service
from app.account.stocks_search import search as stocks_search_fn
from app.core.database import get_db
from app.models.models import Stock, User

router = APIRouter(prefix="/api/v1/account", tags=["account"])


@router.get("/portfolio", response_model=PortfolioListResponse)
async def list_portfolio(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(verify_master_token),
) -> PortfolioListResponse:
    rows = await portfolio_service.list_for_user(db, user.user_id)
    return PortfolioListResponse(positions=[PortfolioPositionOut.model_validate(r) for r in rows])


@router.post("/portfolio", response_model=PortfolioAddResponse)
async def add_portfolio(
    req: PortfolioAddRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(verify_master_token),
) -> PortfolioAddResponse:
    stock = await db.get(Stock, req.ts_code)
    if stock is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="股票代码不存在")
    try:
        pos = await portfolio_service.add(db, user.user_id, req.ts_code, stock.name)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已在持仓中")
    return PortfolioAddResponse(position=PortfolioPositionOut.model_validate(pos))


@router.delete("/portfolio/{ts_code}", response_model=OkResponse)
async def delete_portfolio(
    ts_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(verify_master_token),
) -> OkResponse:
    ok = await portfolio_service.remove(db, user.user_id, ts_code)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="持仓不存在")
    return OkResponse()


@router.get("/stocks/search", response_model=StockSearchResponse)
async def stocks_search(
    q: str = "",
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_master_token),
) -> StockSearchResponse:
    items = await stocks_search_fn(db, q, limit)
    return StockSearchResponse(items=items)
