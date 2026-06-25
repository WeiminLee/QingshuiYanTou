"""验证 Sub-Project 1 的 ORM 模型定义正确"""
from sqlalchemy import inspect


def test_user_model_exists():
    from app.models.models import User
    cols = {c.name for c in inspect(User).columns}
    assert "user_id" in cols
    assert "display_name" in cols
    assert "is_active" in cols
    assert "created_at" in cols
    assert "updated_at" in cols
    # user_id 是主键
    assert "user_id" in {c.name for c in inspect(User).primary_key}


def test_portfolio_position_model_exists():
    from app.models.models import PortfolioPosition
    cols = {c.name for c in inspect(PortfolioPosition).columns}
    assert "id" in cols
    assert "user_id" in cols
    assert "ts_code" in cols
    assert "stock_name" in cols
    assert "created_at" in cols


def test_portfolio_position_unique_constraint():
    from app.models.models import PortfolioPosition
    table = PortfolioPosition.__table__
    uqs = set()
    for uc in table.constraints:
        if hasattr(uc, "columns"):
            uqs.add(tuple(sorted(uc.columns.keys())))
    assert ("ts_code", "user_id") in uqs
