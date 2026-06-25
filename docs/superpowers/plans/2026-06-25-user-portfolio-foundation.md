# Sub-Project 1: 用户与持仓基础 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在"清水投研"系统新增多用户身份 + 个人持仓的最小可用基础，保留现有管理类 API Key 鉴权不变。

**Architecture:** 新增 `app/account/` 子包（与 knowledge/reasoning/data_pipeline 平级）。数据层用现有 PostgreSQL，新增 `users` 和 `portfolio_positions` 两张表。鉴权采用双轨：现有 `X-API-Key` 走管理；新增 HttpOnly `master_token` Cookie + `user_id` Cookie 走用户态。前端新增 3 个页面 + 全局路由守卫。YAML 驱动用户列表，PostgreSQL 存持仓。

**Tech Stack:** FastAPI 0.115、SQLAlchemy 2.0 (async)、alembic、PyJWT、Vue 3 + Vite + Element Plus、TDesign Chat

**Spec:** `docs/superpowers/specs/2026-06-25-user-portfolio-foundation-design.md`

---

## Global Constraints

- 所有路径相对仓库根 `/home/lwm/code/QingshuiYanTou`
- 后端 Python 包都在 `backend/app/`，运行命令需先 `cd backend`
- 前端在 `frontend/`，运行命令需先 `cd frontend`，包管理用 `pnpm`
- 既有约定：测试在 `backend/tests/<package>/`，模型在 `app/models/models.py`，DB session 通过 `Depends(get_db)` 注入
- alembic 迁移命名：`NNN_<slug>.py`，本次新文件名为 `023_add_account_tables.py`
- 不引入新依赖（PyJWT 已在 requirements 或可加单行；Element Plus 已在 frontend）
- 每个任务结束后必须 `git commit`；提交信息遵循 `<type>(<scope>): <subject>` 规范
- 所有用户态路由的鉴权依赖：`verify_master_token`（来自 `app.account.deps`），凡涉及"当前用户"的再加 `get_current_user`
- 错误码：401 未登录、403 身份无效、404 资源不存在或不属于当前用户、409 重复添加、422 股票代码格式错误
- 持仓表 `UNIQUE(user_id, ts_code)`；同一只股票不能重复添加
- 不设 token 过期（自部署场景）
- 主密码长度必须 ≥ 8，启动时校验

---

## 1. 文件变更概览

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/app/config.py` | 修改 | 增 MASTER_PASSWORD、ACCOUNT_TOKEN_SECRET_SALT、users_yaml_path 字段 |
| `backend/app/models/models.py` | 修改 | 增 User、PortfolioPosition ORM 类 |
| `backend/app/models/__init__.py` | 修改 | 导出新模型 |
| `backend/app/account/__init__.py` | 创建 | 包标识 |
| `backend/app/account/config.py` | 创建 | 读 users.yaml、token 密钥派生 |
| `backend/app/account/schemas.py` | 创建 | Pydantic schemas |
| `backend/app/account/services/__init__.py` | 创建 | — |
| `backend/app/account/services/user_service.py` | 创建 | 用户加载、yaml 同步、停用 |
| `backend/app/account/services/auth_service.py` | 创建 | 主密码校验、JWT 签发/校验 |
| `backend/app/account/services/portfolio_service.py` | 创建 | 持仓增删查 |
| `backend/app/account/api/__init__.py` | 创建 | — |
| `backend/app/account/api/auth.py` | 创建 | /auth/login,logout,switch-user,whoami |
| `backend/app/account/api/users.py` | 创建 | /users |
| `backend/app/account/api/portfolio.py` | 创建 | /portfolio GET/POST/DELETE |
| `backend/app/account/stocks_search.py` | 创建 | /stocks/search 复用 Tushare stock_basic |
| `backend/app/account/deps.py` | 创建 | verify_master_token、get_current_user |
| `backend/app/main.py` | 修改 | 注册新路由 + lifespan 加用户同步 |
| `backend/alembic/versions/023_add_account_tables.py` | 创建 | 新表迁移 |
| `backend/users.yaml` | 创建 | 用户列表（示例） |
| `backend/.env.example` | 修改 | 增 MASTER_PASSWORD 示例 |
| `backend/tests/account/__init__.py` | 创建 | — |
| `backend/tests/account/conftest.py` | 创建 | fixtures: 临时 yaml、env、db session |
| `backend/tests/account/test_user_service.py` | 创建 | yaml 同步单测 |
| `backend/tests/account/test_auth_service.py` | 创建 | JWT 签发/校验单测 |
| `backend/tests/account/test_portfolio_service.py` | 创建 | 持仓 CRUD + 隔离单测 |
| `backend/tests/account/test_auth_api.py` | 创建 | auth API 集成测 |
| `backend/tests/account/test_portfolio_api.py` | 创建 | portfolio API 集成测 |
| `backend/tests/account/test_stocks_search.py` | 创建 | 搜索端点单测 |
| `frontend/src/api/account.js` | 创建 | axios 封装：login/logout/switch-user/whoami/users/portfolio/stocksSearch |
| `frontend/src/views/LoginView.vue` | 创建 | 登录页 |
| `frontend/src/views/SelectIdentityView.vue` | 创建 | 选身份页 |
| `frontend/src/views/PortfolioView.vue` | 创建 | 持仓页 |
| `frontend/src/router/index.js` | 修改 | 增 /login、/select-identity、/portfolio 路由 + 守卫 |
| `frontend/src/App.vue` 或 `main.js` | 修改 | 启动调 /auth/whoami 决定初始跳转 |
| `README.md` | 修改 | 加"用户与持仓"小节 |

---

## 2. 任务列表

### Task 1: 配置扩展（settings + users.yaml）

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/users.yaml`
- Modify: `backend/.env.example`

**步骤:**

- [ ] **Step 1: 在 settings 中加字段**

在 `backend/app/config.py` 的 `Settings` 类中追加：

```python
# 用户与持仓基础（Sub-Project 1）
master_password: str = Field(default="", description="主密码（启动校验长度>=8）")
account_token_secret_salt: str = Field(
    default="dev-salt-do-not-use-in-prod",
    description="JWT 签名盐；生产请用环境变量覆盖",
)
users_yaml_path: Path = Field(
    default=Path(__file__).resolve().parent.parent / "users.yaml",
    description="用户列表 yaml 路径",
)
```

- [ ] **Step 2: 创建 `backend/users.yaml`**

```yaml
users:
  - user_id: lwm
    display_name: 老王
  - user_id: partner_a
    display_name: 合伙人甲
```

- [ ] **Step 3: 在 `.env.example` 中追加**

```
# Sub-Project 1: 主密码（必填，长度>=8）
MASTER_PASSWORD=changeme-strong-password
# 可选：JWT 签名盐（不填用 dev 默认值，生产务必覆盖）
ACCOUNT_TOKEN_SECRET_SALT=random-string-here
```

- [ ] **Step 4: 写 settings 加载测试**

`backend/tests/account/__init__.py` 留空。`backend/tests/account/test_settings.py`：

```python
"""验证 Sub-Project 1 相关的 settings 字段被正确加载"""
import os
from pathlib import Path


def test_master_password_loaded(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-pass-1234")
    # 重新加载 settings（避免 cache）
    from importlib import reload
    from app import config as cfg_mod
    reload(cfg_mod)
    assert cfg_mod.settings.master_password == "test-pass-1234"


def test_users_yaml_path_default_exists():
    from app.config import settings
    assert settings.users_yaml_path.name == "users.yaml"
    assert settings.users_yaml_path.exists()
```

- [ ] **Step 5: 跑测试**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_settings.py -v
# 预期: 2 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/users.yaml backend/.env.example backend/tests/account/
git commit -m "feat(account): add master_password and users.yaml settings"
```

---

### Task 2: ORM 模型（User + PortfolioPosition）

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/account/test_models.py`

**步骤:**

- [ ] **Step 1: 写模型 schema 测试**

`backend/tests/account/test_models.py`：

```python
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
    uqs = {tuple(sorted(uc.columns.keys())) for uc in inspect(PortfolioPosition).constraints if hasattr(uc, "columns")}
    assert ("ts_code", "user_id") in uqs
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_models.py -v
# 预期: ImportError 或 AttributeError
```

- [ ] **Step 3: 在 `models.py` 追加模型类**

在 `backend/app/models/models.py` 文件末尾追加：

```python
class User(Base):
    """Sub-Project 1: 多用户体系的用户表
    启动时由 users.yaml 同步，运行期只读
    """
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PortfolioPosition(Base):
    """Sub-Project 1: 用户持仓表（极简版）
    字段：用户ID + 股票代码 + 股票名称 + 加入时间
    """
    __tablename__ = "portfolio_positions"
    __table_args__ = (
        UniqueConstraint("user_id", "ts_code", name="uq_portfolio_user_ts_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.user_id"), nullable=False, index=True
    )
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: 在 `app/models/__init__.py` 导出**

确认 `backend/app/models/__init__.py` 顶部有 `from .models import (...)`。在导入列表的"用户数据"组别下追加：

```python
# Sub-Project 1: 用户与持仓
User,
PortfolioPosition,
```

（视当前文件中已有结构合并到合适的分组；如果有 `__all__` 也要补上）

- [ ] **Step 5: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_models.py -v
# 预期: 3 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/models.py backend/app/models/__init__.py backend/tests/account/test_models.py
git commit -m "feat(account): add User and PortfolioPosition ORM models"
```

---

### Task 3: Alembic 迁移 023

**Files:**
- Create: `backend/alembic/versions/023_add_account_tables.py`

**步骤:**

- [ ] **Step 1: 读最近的迁移头部约定**

```bash
cd backend
head -25 alembic/versions/022_add_ingestion_jobs.py
```

确认 down_revision 是 `021`，以及 `from typing import Sequence, Union` 等导入。

- [ ] **Step 2: 创建迁移文件**

`backend/alembic/versions/023_add_account_tables.py`：

```python
"""add account tables (users, portfolio_positions)

Revision ID: 023
Revises: 022
Create Date: 2026-06-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023"
down_revision: Union[str, Sequence[str], None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("ts_code", sa.String(16), nullable=False),
        sa.Column("stock_name", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "ts_code", name="uq_portfolio_user_ts_code"),
    )
    op.create_index(
        "ix_portfolio_positions_user_id",
        "portfolio_positions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_positions_user_id", table_name="portfolio_positions")
    op.drop_table("portfolio_positions")
    op.drop_table("users")
```

- [ ] **Step 3: 应用迁移**

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
# 预期: Running upgrade 022 -> 023, add account tables (users, portfolio_positions)
```

- [ ] **Step 4: 验证表已创建**

```bash
docker exec -it qingshui_postgres psql -U qingshui -d qingshui -c "\d users"
docker exec -it qingshui_postgres psql -U qingshui -d qingshui -c "\d portfolio_positions"
# 预期: 两张表的 schema 正确显示
```

- [ ] **Step 5: 跑现有测试确保未破坏**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -x -q --ignore=tests/test_e2e_agent.py
# 预期: 全部通过
```

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/023_add_account_tables.py
git commit -m "feat(account): alembic migration 023 add users and portfolio_positions"
```

---

### Task 4: account 包骨架 + config 模块

**Files:**
- Create: `backend/app/account/__init__.py`
- Create: `backend/app/account/config.py`
- Create: `backend/tests/account/conftest.py`

**步骤:**

- [ ] **Step 1: 写 `__init__.py`**

`backend/app/account/__init__.py`：

```python
"""account: 用户与持仓基础（Sub-Project 1）"""
```

- [ ] **Step 2: 写 conftest.py 共享 fixtures**

`backend/tests/account/conftest.py`：

```python
"""Sub-Project 1 测试 fixtures"""
import os
import tempfile
from pathlib import Path
import pytest
import pytest_asyncio


@pytest.fixture
def temp_users_yaml(tmp_path):
    """临时 yaml 路径，内容是示例用户"""
    yaml_path = tmp_path / "users.yaml"
    yaml_path.write_text(
        "users:\n"
        "  - user_id: alice\n"
        "    display_name: Alice\n"
        "  - user_id: bob\n"
        "    display_name: Bob\n",
        encoding="utf-8",
    )
    return yaml_path


@pytest.fixture
def master_password_env(monkeypatch):
    """保证主密码满足长度要求"""
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    return "test-master-pass-1234"
```

- [ ] **Step 3: 写 `account/config.py` 测试**

`backend/tests/account/test_account_config.py`：

```python
"""测试 account 子包的 config：yaml 加载、token 盐派生、主密码校验"""
import pytest
from app.account import config as account_cfg


def test_load_users_from_yaml(temp_users_yaml):
    users = account_cfg.load_users_from_yaml(temp_users_yaml)
    assert [u.user_id for u in users] == ["alice", "bob"]
    assert users[0].display_name == "Alice"


def test_load_users_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        account_cfg.load_users_from_yaml(tmp_path / "no-such.yaml")


def test_derive_token_secret(master_password_env):
    secret = account_cfg.derive_token_secret()
    assert isinstance(secret, str) and len(secret) >= 32
    # 同一进程派生稳定
    assert account_cfg.derive_token_secret() == secret


def test_validate_master_password_ok(master_password_env):
    account_cfg.validate_master_password()  # 不抛


def test_validate_master_password_too_short(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "short")
    with pytest.raises(ValueError, match="长度"):
        account_cfg.validate_master_password()
```

- [ ] **Step 4: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_account_config.py -v
# 预期: ImportError 或 AttributeError
```

- [ ] **Step 5: 实现 `account/config.py`**

`backend/app/account/config.py`：

```python
"""account 子包配置：读 users.yaml、派生 token 密钥、校验主密码"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml

from app.config import settings


@dataclass(frozen=True)
class YamlUser:
    user_id: str
    display_name: str


def load_users_from_yaml(path: Path | None = None) -> List[YamlUser]:
    """读取 users.yaml，返回用户列表；文件不存在或解析失败抛错"""
    p = path or settings.users_yaml_path
    if not p.exists():
        raise FileNotFoundError(f"users.yaml 不存在: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raw_users = data.get("users", [])
    if not isinstance(raw_users, list):
        raise ValueError("users.yaml 顶层 users 字段必须是列表")
    out: List[YamlUser] = []
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
    raw = f"{settings.master_password}|{settings.account_token_secret_salt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_master_password() -> None:
    """启动时调用：长度 < 8 抛 ValueError"""
    if not settings.master_password or len(settings.master_password) < 8:
        raise ValueError("MASTER_PASSWORD 未设置或长度 < 8（请在 backend/.env 配置）")
```

- [ ] **Step 6: 添加 PyYAML 依赖（如果未在 requirements.txt）**

```bash
cd backend
grep -q "^PyYAML" requirements.txt || echo "PyYAML>=6.0" >> requirements.txt
```

- [ ] **Step 7: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_account_config.py -v
# 预期: 5 passed
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/account/__init__.py backend/app/account/config.py backend/tests/account/conftest.py backend/tests/account/test_account_config.py backend/requirements.txt
git commit -m "feat(account): add account/config module with yaml loader and password validator"
```

---

### Task 5: user_service（yaml 同步 + 加载）

**Files:**
- Create: `backend/app/account/services/__init__.py`
- Create: `backend/app/account/services/user_service.py`
- Create: `backend/tests/account/test_user_service.py`

**步骤:**

- [ ] **Step 1: 写 `__init__.py`**

`backend/app/account/services/__init__.py`：

```python
"""account 子包的服务层"""
```

- [ ] **Step 2: 写 user_service 测试**

`backend/tests/account/test_user_service.py`：

```python
"""user_service: yaml 同步、活跃用户查询"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.models import User
from app.account.services import user_service


@pytest.fixture
async def db_session():
    """内存 SQLite 异步 session（仅 user_service 内部 get_active 用得到）"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def test_sync_creates_new_users(db_session, temp_users_yaml):
    n = await user_service.sync_from_yaml(db_session, temp_users_yaml)
    assert n == 2
    rows = (await db_session.execute(User.__table__.select())).fetchall()
    ids = {r[0] for r in rows}
    assert ids == {"alice", "bob"}


async def test_sync_updates_display_name(db_session, temp_users_yaml):
    await user_service.sync_from_yaml(db_session, temp_users_yaml)
    # 改 yaml 里的名字
    temp_users_yaml.write_text(
        "users:\n  - user_id: alice\n    display_name: Alice2\n  - user_id: bob\n    display_name: Bob\n",
        encoding="utf-8",
    )
    await user_service.sync_from_yaml(db_session, temp_users_yaml)
    u = await user_service.get_active(db_session, "alice")
    assert u.display_name == "Alice2"
    assert u.is_active is True


async def test_sync_deactivates_removed_user(db_session, temp_users_yaml):
    await user_service.sync_from_yaml(db_session, temp_users_yaml)
    # yaml 里去掉 bob
    temp_users_yaml.write_text(
        "users:\n  - user_id: alice\n    display_name: Alice\n",
        encoding="utf-8",
    )
    await user_service.sync_from_yaml(db_session, temp_users_yaml)
    u = await user_service.get_active(db_session, "bob")
    assert u is None  # 已停用，get_active 过滤掉


async def test_get_active_returns_none_for_missing(db_session):
    u = await user_service.get_active(db_session, "ghost")
    assert u is None
```

> 注意：SQLite 不支持 PG 特有的 JSONB 等。User 表本身没用这些，足够。如要严格 PG 行为可改用 docker postgres + 测试 session；优先 SQLite 提速。

- [ ] **Step 3: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_user_service.py -v
# 预期: ImportError
```

- [ ] **Step 4: 实现 user_service**

`backend/app/account/services/user_service.py`：

```python
"""用户服务：yaml 同步 + 活跃查询"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.account import config as account_cfg
from app.models.models import User


async def sync_from_yaml(session: AsyncSession, yaml_path: Path | None = None) -> int:
    """根据 yaml 同步到 DB：
    - 新出现的 user_id: 插入，is_active=true
    - 已存在的 user_id: 更新 display_name、updated_at
    - yaml 中不存在的 user_id: 置 is_active=false
    返回活跃用户数。
    """
    yaml_users = account_cfg.load_users_from_yaml(yaml_path)
    yaml_ids = {u.user_id for u in yaml_users}

    # 1) upsert yaml 中的用户
    for yu in yaml_users:
        existing = await session.get(User, yu.user_id)
        if existing is None:
            session.add(User(user_id=yu.user_id, display_name=yu.display_name, is_active=True))
        else:
            existing.display_name = yu.display_name
            existing.is_active = True
    # 2) 标记 yaml 中不存在的为非活跃
    result = await session.execute(select(User))
    for row in result.scalars():
        if row.user_id not in yaml_ids:
            row.is_active = False
    await session.commit()

    # 3) 统计活跃
    active_q = await session.execute(select(User).where(User.is_active.is_(True)))
    return len(list(active_q.scalars()))


async def get_active(session: AsyncSession, user_id: str) -> Optional[User]:
    """返回活跃用户；不存在或已停用返回 None"""
    u = await session.get(User, user_id)
    if u is None or not u.is_active:
        return None
    return u


async def list_active(session: AsyncSession) -> list[User]:
    """所有活跃用户"""
    result = await session.execute(select(User).where(User.is_active.is_(True)).order_by(User.user_id))
    return list(result.scalars())
```

- [ ] **Step 5: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_user_service.py -v
# 预期: 4 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/account/services/user_service.py backend/tests/account/test_user_service.py
git commit -m "feat(account): add user_service with yaml sync and active user lookup"
```

---

### Task 6: auth_service（密码 + JWT）

**Files:**
- Create: `backend/app/account/services/auth_service.py`
- Create: `backend/tests/account/test_auth_service.py`

**步骤:**

- [ ] **Step 1: 写 auth_service 测试**

`backend/tests/account/test_auth_service.py`：

```python
"""auth_service: 主密码校验、JWT 签发/校验"""
import time
import pytest

from app.account import config as account_cfg
from app.account.services import auth_service


@pytest.fixture
def with_master_pw(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    # 重新加载 settings
    from importlib import reload
    from app import config as cfg_mod
    reload(cfg_mod)


def test_verify_master_password_ok(with_master_pw):
    assert auth_service.verify_master_password("test-master-pass-1234") is True


def test_verify_master_password_wrong(with_master_pw):
    assert auth_service.verify_master_password("wrong") is False


def test_issue_and_verify_token(with_master_pw):
    token = auth_service.issue_master_token()
    assert auth_service.verify_master_token(token) is True


def test_verify_token_tampered(with_master_pw):
    token = auth_service.issue_master_token()
    bad = token[:-2] + ("AB" if token[-2:] != "AB" else "CD")
    assert auth_service.verify_master_token(bad) is False


def test_verify_token_empty(with_master_pw):
    assert auth_service.verify_master_token("") is False
    assert auth_service.verify_master_token(None) is False
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_auth_service.py -v
# 预期: ImportError
```

- [ ] **Step 3: 添加 PyJWT 依赖（如果未在 requirements.txt）**

```bash
cd backend
grep -q "^PyJWT" requirements.txt || echo "PyJWT>=2.8" >> requirements.txt
```

- [ ] **Step 4: 实现 auth_service**

`backend/app/account/services/auth_service.py`：

```python
"""认证服务：主密码校验 + master_token 签发/校验"""
from __future__ import annotations

import time
from typing import Optional

import jwt

from app.account import config as account_cfg
from app.config import settings


# token 类型标识；以后加 user_token / admin_token 可区分
TOKEN_TYPE_MASTER = "master"


def verify_master_password(password: str) -> bool:
    """常数时间比较，避免计时攻击；不抛错"""
    if not password:
        return False
    expected = settings.master_password or ""
    if not expected:
        return False
    # hmac.compare_digest 是常数时间
    import hmac
    return hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))


def issue_master_token() -> str:
    """签发一个 master token，过期时间 = 当前时间 + 50 年（"永不过期"的实用近似）"""
    secret = account_cfg.derive_token_secret()
    now = int(time.time())
    payload = {
        "iat": now,
        # 50 年后过期；后续要做"软过期"机制时改这里
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
```

- [ ] **Step 5: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_auth_service.py -v
# 预期: 5 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/account/services/auth_service.py backend/tests/account/test_auth_service.py backend/requirements.txt
git commit -m "feat(account): add auth_service with master password and JWT"
```

---

### Task 7: portfolio_service（CRUD + 隔离）

**Files:**
- Create: `backend/app/account/services/portfolio_service.py`
- Create: `backend/tests/account/test_portfolio_service.py`

**步骤:**

- [ ] **Step 1: 写 portfolio_service 测试**

`backend/tests/account/test_portfolio_service.py`：

```python
"""portfolio_service: 持仓增删查 + 跨用户隔离"""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.models import PortfolioPosition, User
from app.account.services import portfolio_service


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(PortfolioPosition.__table__.create)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        # 预置两个用户
        session.add_all([
            User(user_id="alice", display_name="Alice"),
            User(user_id="bob", display_name="Bob"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def test_add_and_list(db_session):
    p = await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    assert p.ts_code == "600519.SH"
    rows = await portfolio_service.list_for_user(db_session, "alice")
    assert [r.ts_code for r in rows] == ["600519.SH"]


async def test_add_duplicate_raises(db_session):
    await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    with pytest.raises(IntegrityError):
        await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    await db_session.rollback()


async def test_list_isolates_users(db_session):
    await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    await portfolio_service.add(db_session, "bob", "300750.SZ", "宁德时代")
    a_rows = await portfolio_service.list_for_user(db_session, "alice")
    b_rows = await portfolio_service.list_for_user(db_session, "bob")
    assert [r.ts_code for r in a_rows] == ["600519.SH"]
    assert [r.ts_code for r in b_rows] == ["300750.SZ"]


async def test_remove_own(db_session):
    await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    ok = await portfolio_service.remove(db_session, "alice", "600519.SH")
    assert ok is True
    rows = await portfolio_service.list_for_user(db_session, "alice")
    assert rows == []


async def test_remove_other_user_returns_false(db_session):
    await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    ok = await portfolio_service.remove(db_session, "bob", "600519.SH")
    assert ok is False
    rows = await portfolio_service.list_for_user(db_session, "alice")
    assert [r.ts_code for r in rows] == ["600519.SH"]


async def test_remove_nonexistent_returns_false(db_session):
    ok = await portfolio_service.remove(db_session, "alice", "999999.SH")
    assert ok is False
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_portfolio_service.py -v
# 预期: ImportError
```

- [ ] **Step 3: 实现 portfolio_service**

`backend/app/account/services/portfolio_service.py`：

```python
"""持仓服务：增删查，严格按 user_id 隔离"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import PortfolioPosition


async def add(session: AsyncSession, user_id: str, ts_code: str, stock_name: str) -> PortfolioPosition:
    """添加持仓；重复抛 IntegrityError（让上层映射 409）"""
    pos = PortfolioPosition(user_id=user_id, ts_code=ts_code, stock_name=stock_name)
    session.add(pos)
    await session.commit()
    await session.refresh(pos)
    return pos


async def list_for_user(session: AsyncSession, user_id: str) -> List[PortfolioPosition]:
    """列出某用户的所有持仓，按 created_at desc"""
    result = await session.execute(
        select(PortfolioPosition)
        .where(PortfolioPosition.user_id == user_id)
        .order_by(PortfolioPosition.created_at.desc())
    )
    return list(result.scalars())


async def remove(session: AsyncSession, user_id: str, ts_code: str) -> bool:
    """删除持仓；只删自己的，删别人的返回 False（不抛错，路由层映射 404）"""
    result = await session.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.user_id == user_id,
            PortfolioPosition.ts_code == ts_code,
        )
    )
    pos = result.scalar_one_or_none()
    if pos is None:
        return False
    await session.delete(pos)
    await session.commit()
    return True
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_portfolio_service.py -v
# 预期: 6 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/account/services/portfolio_service.py backend/tests/account/test_portfolio_service.py
git commit -m "feat(account): add portfolio_service with strict user isolation"
```

---

### Task 8: deps（FastAPI 依赖）

**Files:**
- Create: `backend/app/account/deps.py`
- Create: `backend/tests/account/test_deps.py`

**步骤:**

- [ ] **Step 1: 写 deps 测试**

`backend/tests/account/test_deps.py`：

```python
"""FastAPI Depends: verify_master_token + get_current_user"""
import pytest
from fastapi import HTTPException

from app.account import deps as account_deps


class _FakeRequest:
    def __init__(self, cookies: dict | None = None):
        self.cookies = cookies or {}


async def test_verify_master_token_ok(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload
    from app import config as cfg_mod
    reload(cfg_mod)
    from app.account.services import auth_service
    token = auth_service.issue_master_token()
    await account_deps.verify_master_token(_FakeRequest({"master_token": token}))  # 不抛


async def test_verify_master_token_missing(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload
    from app import config as cfg_mod
    reload(cfg_mod)
    with pytest.raises(HTTPException) as ei:
        await account_deps.verify_master_token(_FakeRequest({}))
    assert ei.value.status_code == 401


async def test_get_current_user_no_cookie(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload
    from app import config as cfg_mod
    reload(cfg_mod)
    with pytest.raises(HTTPException) as ei:
        await account_deps.get_current_user(_FakeRequest({}))
    assert ei.value.status_code == 401
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_deps.py -v
# 预期: ImportError
```

- [ ] **Step 3: 实现 deps**

`backend/app/account/deps.py`：

```python
"""FastAPI Depends：用户态接口的鉴权"""
from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.services import auth_service
from app.models.models import User


async def verify_master_token(request: Request) -> None:
    """校验 master_token cookie；失败 401"""
    token = request.cookies.get("master_token")
    if not auth_service.verify_master_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或会话失效",
        )


async def get_current_user(
    request: Request,
    db: AsyncSession,
) -> User:
    """从 user_id cookie 取当前用户；失败 401"""
    from app.account.services import user_service

    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未选择身份",
        )
    user = await user_service.get_active(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="身份无效或已停用",
        )
    return user
```

> 注意：FastAPI Depends 的写法要求 `db` 也是一个 Depends。这里我们**声明**了 `db: AsyncSession` 参数但没标 `Depends`，FastAPI 会识别为子依赖。但更稳妥的写法是从 `app.core.database` 显式 `Depends(get_db)`，这里需要把 `get_db` 路径搞清楚：

```python
# 更稳妥版（请用这个）：
from app.core.database import get_db

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    ...
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_deps.py -v
# 预期: 3 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/account/deps.py backend/tests/account/test_deps.py
git commit -m "feat(account): add FastAPI deps for master_token and current_user"
```

---

### Task 9: schemas（Pydantic）

**Files:**
- Create: `backend/app/account/schemas.py`
- Create: `backend/tests/account/test_schemas.py`

**步骤:**

- [ ] **Step 1: 写 schemas 测试**

`backend/tests/account/test_schemas.py`：

```python
"""Pydantic schemas 的字段和校验"""
import pytest
from pydantic import ValidationError

from app.account.schemas import (
    LoginRequest,
    SwitchUserRequest,
    PortfolioAddRequest,
)


def test_login_request():
    obj = LoginRequest(password="abc12345")
    assert obj.password == "abc12345"


def test_login_request_too_short():
    with pytest.raises(ValidationError):
        LoginRequest(password="")


def test_switch_user_request():
    obj = SwitchUserRequest(user_id="alice")
    assert obj.user_id == "alice"


def test_portfolio_add_request_ts_code_format():
    # 合法
    PortfolioAddRequest(ts_code="600519.SH")
    # 缺 .SZ/.SH 等后缀
    with pytest.raises(ValidationError):
        PortfolioAddRequest(ts_code="600519")
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_schemas.py -v
# 预期: ImportError
```

- [ ] **Step 3: 实现 schemas**

`backend/app/account/schemas.py`：

```python
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
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_schemas.py -v
# 预期: 4 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/account/schemas.py backend/tests/account/test_schemas.py
git commit -m "feat(account): add Pydantic schemas for account/portfolio API"
```

---

### Task 10: stocks_search（复用 Tushare stock_basic）

**Files:**
- Create: `backend/app/account/stocks_search.py`
- Create: `backend/tests/account/test_stocks_search.py`

**步骤:**

- [ ] **Step 1: 探查现有 stock 模型字段**

```bash
cd backend
grep -A 20 "class Stock" app/models/models.py | head -30
```

记录 `ts_code`、`name`（或 `symbol`+`name`）、`industry` 等字段名。

- [ ] **Step 2: 写 stocks_search 测试**

`backend/tests/account/test_stocks_search.py`：

```python
"""stocks_search 复用 Tushare stock_basic 表做模糊匹配"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.models import Stock
from app.account import stocks_search


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Stock.__table__.create)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add_all([
            Stock(ts_code="600519.SH", name="贵州茅台", industry="白酒"),
            Stock(ts_code="300750.SZ", name="宁德时代", industry="电池"),
            Stock(ts_code="000001.SZ", name="平安银行", industry="银行"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def test_search_by_name(db_session):
    items = await stocks_search.search(db_session, "茅台", limit=10)
    assert any(i.ts_code == "600519.SH" for i in items)


async def test_search_by_ts_code_prefix(db_session):
    items = await stocks_search.search(db_session, "300750", limit=10)
    assert any(i.ts_code == "300750.SZ" for i in items)


async def test_search_limit(db_session):
    items = await stocks_search.search(db_session, "", limit=2)
    assert len(items) <= 2
```

- [ ] **Step 3: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_stocks_search.py -v
# 预期: ImportError
```

- [ ] **Step 4: 实现 stocks_search**

> ⚠️ 字段名要按 Step 1 探查的实际 Stock 表调整（特别是 `name` vs `symbol`）。下面用最常见的命名。

`backend/app/account/stocks_search.py`：

```python
"""股票搜索：复用现有 stocks 表（来自 Tushare stock_basic 同步）"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.schemas import StockSearchItem
from app.models.models import Stock


async def search(session: AsyncSession, q: str, limit: int = 10) -> List[StockSearchItem]:
    """在 stocks 表里做模糊匹配：ts_code 前缀 OR name 包含 q
    q 为空时按 ts_code 升序返回前 limit 条
    limit 上限 20
    """
    limit = max(1, min(limit, 20))
    q = (q or "").strip()
    stmt = select(Stock)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Stock.name.ilike(like), Stock.ts_code.ilike(f"{q}%")))  # type: ignore[attr-defined]
    stmt = stmt.order_by(Stock.ts_code).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        StockSearchItem(
            ts_code=r.ts_code,
            name=getattr(r, "name", "") or "",
            industry=getattr(r, "industry", None),
        )
        for r in rows
    ]
```

> 如果 Stock 表实际叫 `symbol` 不是 `name`，请相应替换，并调整测试。

- [ ] **Step 5: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_stocks_search.py -v
# 预期: 3 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/account/stocks_search.py backend/tests/account/test_stocks_search.py
git commit -m "feat(account): add stocks_search reusing existing stock_basic table"
```

---

### Task 11: API 路由 — auth + users

**Files:**
- Create: `backend/app/account/api/__init__.py`
- Create: `backend/app/account/api/auth.py`
- Create: `backend/app/account/api/users.py`
- Create: `backend/tests/account/test_auth_api.py`

**步骤:**

- [ ] **Step 1: 写 `__init__.py`**

`backend/app/account/api/__init__.py`：

```python
"""account 子包的 API 路由"""
```

- [ ] **Step 2: 写 auth API 测试**

`backend/tests/account/test_auth_api.py`：

```python
"""集成测：/api/v1/auth/* 和 /api/v1/users"""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models.models import User
from app.config import settings


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    # 重置 settings 缓存
    from importlib import reload
    from app import config as cfg_mod
    reload(cfg_mod)

    # 内存 SQLite
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
    # 替换 app.core.database 的 engine 和 get_db
    from app.core import database as db_mod
    db_mod.engine = engine
    db_mod.async_session = async_sessionmaker(engine, expire_on_commit=False)

    # 替换 lifespan 里用的 DB session
    async def _override_get_db():
        async with db_mod.async_session() as s:
            yield s
    app.dependency_overrides[db_mod.get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 预置用户
        async with db_mod.async_session() as s:
            s.add_all([
                User(user_id="alice", display_name="Alice"),
                User(user_id="bob", display_name="Bob"),
            ])
            await s.commit()
        yield c
    app.dependency_overrides.clear()


async def test_login_success_and_whoami(client):
    r = await client.post("/api/v1/auth/login", json={"password": "test-master-pass-1234"})
    assert r.status_code == 200
    assert "master_token" in r.cookies
    body = r.json()
    assert body["ok"] is True
    assert {u["user_id"] for u in body["users"]} == {"alice", "bob"}

    # whoami
    r = await client.get("/api/v1/auth/whoami")
    assert r.status_code == 200
    body = r.json()
    assert body["user"] is None
    assert {u["user_id"] for u in body["users"]} == {"alice", "bob"}


async def test_login_wrong_password(client):
    r = await client.post("/api/v1/auth/login", json={"password": "wrong"})
    assert r.status_code == 401


async def test_switch_user_and_whoami(client):
    await client.post("/api/v1/auth/login", json={"password": "test-master-pass-1234"})
    r = await client.post("/api/v1/auth/switch-user", json={"user_id": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["current_user"]["user_id"] == "alice"

    r = await client.get("/api/v1/auth/whoami")
    body = r.json()
    assert body["user"]["user_id"] == "alice"


async def test_users_list_requires_login(client):
    r = await client.get("/api/v1/users")
    assert r.status_code == 401


async def test_logout_clears_cookie(client):
    await client.post("/api/v1/auth/login", json={"password": "test-master-pass-1234"})
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    r = await client.get("/api/v1/auth/whoami")
    assert r.status_code == 401
```

- [ ] **Step 3: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_auth_api.py -v
# 预期: ImportError 或 404
```

- [ ] **Step 4: 实现 auth API**

`backend/app/account/api/auth.py`：

```python
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
    UserBriefList,
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
        # 生产环境应该 secure=True（仅 HTTPS），自部署默认开
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
```

- [ ] **Step 5: 实现 users API**

`backend/app/account/api/users.py`：

```python
"""/api/v1/users 路由：列出可选身份"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.deps import verify_master_token
from app.account.schemas import UserBrief, UserBriefList
from app.account.services import user_service
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/users", tags=["account"])


@router.get("", response_model=UserBriefList)
async def list_users(
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_master_token),
) -> UserBriefList:
    users = await user_service.list_active(db)
    return UserBriefList(users=[UserBrief.model_validate(u) for u in users])
```

- [ ] **Step 6: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_auth_api.py -v
# 预期: 5 passed
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/account/api/ backend/tests/account/test_auth_api.py
git commit -m "feat(account): add auth and users API routers"
```

---

### Task 12: API 路由 — portfolio + stocks_search

**Files:**
- Create: `backend/app/account/api/portfolio.py`
- Create: `backend/tests/account/test_portfolio_api.py`

**步骤:**

- [ ] **Step 1: 写 portfolio API 测试**

`backend/tests/account/test_portfolio_api.py`：

```python
"""集成测：/api/v1/portfolio 和 /api/v1/stocks/search"""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models.models import PortfolioPosition, Stock, User
from app.core import database as db_mod


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload
    from app import config as cfg_mod
    reload(cfg_mod)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(PortfolioPosition.__table__.create)
        await conn.run_sync(Stock.__table__.create)
    db_mod.engine = engine
    db_mod.async_session = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with db_mod.async_session() as s:
            yield s
    app.dependency_overrides[db_mod.get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with db_mod.async_session() as s:
            s.add_all([
                User(user_id="alice", display_name="Alice"),
                User(user_id="bob", display_name="Bob"),
                Stock(ts_code="600519.SH", name="贵州茅台", industry="白酒"),
                Stock(ts_code="300750.SZ", name="宁德时代", industry="电池"),
            ])
            await s.commit()
        yield c
    app.dependency_overrides.clear()


async def _login_and_switch(client, user_id: str) -> None:
    r = await client.post("/api/v1/auth/login", json={"password": "test-master-pass-1234"})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/switch-user", json={"user_id": user_id})
    assert r.status_code == 200


async def test_portfolio_lifecycle(client):
    await _login_and_switch(client, "alice")
    r = await client.get("/api/v1/portfolio")
    assert r.status_code == 200
    assert r.json()["positions"] == []

    r = await client.post("/api/v1/portfolio", json={"ts_code": "600519.SH"})
    assert r.status_code == 200
    assert r.json()["position"]["ts_code"] == "600519.SH"

    r = await client.get("/api/v1/portfolio")
    assert len(r.json()["positions"]) == 1

    r = await client.delete("/api/v1/portfolio/600519.SH")
    assert r.status_code == 200
    r = await client.get("/api/v1/portfolio")
    assert r.json()["positions"] == []


async def test_portfolio_duplicate_returns_409(client):
    await _login_and_switch(client, "alice")
    await client.post("/api/v1/portfolio", json={"ts_code": "600519.SH"})
    r = await client.post("/api/v1/portfolio", json={"ts_code": "600519.SH"})
    assert r.status_code == 409


async def test_portfolio_invalid_ts_code_returns_422(client):
    await _login_and_switch(client, "alice")
    r = await client.post("/api/v1/portfolio", json={"ts_code": "badcode"})
    assert r.status_code == 422


async def test_portfolio_isolates_users(client):
    await _login_and_switch(client, "alice")
    await client.post("/api/v1/portfolio", json={"ts_code": "600519.SH"})

    await _login_and_switch(client, "bob")
    r = await client.get("/api/v1/portfolio")
    assert r.json()["positions"] == []
    r = await client.delete("/api/v1/portfolio/600519.SH")
    assert r.status_code == 404  # bob 没有 600519.SH


async def test_stocks_search(client):
    await _login_and_switch(client, "alice")
    r = await client.get("/api/v1/stocks/search", params={"q": "茅台"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["ts_code"] == "600519.SH" for i in items)
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_portfolio_api.py -v
# 预期: ImportError 或 404
```

- [ ] **Step 3: 实现 portfolio API**

`backend/app/account/api/portfolio.py`：

```python
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

router = APIRouter(prefix="/api/v1", tags=["account"])


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
    # 校验 ts_code 存在于 stocks 表
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
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/test_portfolio_api.py -v
# 预期: 5 passed
```

- [ ] **Step 5: 跑全部 account 测试**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/account/ -v
# 预期: 全部通过（约 30+ 用例）
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/account/api/portfolio.py backend/tests/account/test_portfolio_api.py
git commit -m "feat(account): add portfolio and stocks_search API routers"
```

---

### Task 13: 接入主应用（main.py + lifespan）

**Files:**
- Modify: `backend/app/main.py`

**步骤:**

- [ ] **Step 1: 引入新路由**

在 `backend/app/main.py` 顶部加：

```python
from app.account.api import auth as account_auth_router
from app.account.api import users as account_users_router
from app.account.api import portfolio as account_portfolio_router
```

在路由注册区追加：

```python
app.include_router(account_auth_router.router)
app.include_router(account_users_router.router)
app.include_router(account_portfolio_router.router)
```

- [ ] **Step 2: 在 lifespan 加用户同步**

在 `backend/app/main.py` 的 `lifespan` 异步生成器中，在 `StockNameResolver` 预热之后、yield 之前加：

```python
# Sub-Project 1: 校验主密码 + 同步 users.yaml
from app.account import config as account_cfg
from app.account.services import user_service
from app.core.database import async_session

account_cfg.validate_master_password()
async with async_session() as s:
    n = await user_service.sync_from_yaml(s)
    print(f"已同步 {n} 个用户: {[u.user_id for u in (await user_service.list_active(s))]}")
```

- [ ] **Step 3: 启动应用，确认 lifespan 阶段无误**

```bash
cd backend
source .venv/bin/activate
MASTER_PASSWORD=test-pass-1234 python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
sleep 3
# 预期日志含 "已同步 2 个用户: [...]"
curl -s http://localhost:8000/health
# 预期: {"status":"ok"}
kill $SERVER_PID
```

- [ ] **Step 4: 跑全部测试**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -x -q
# 预期: 全部通过
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(account): wire account routers into main app and lifespan"
```

---

### Task 14: 前端 axios 封装

**Files:**
- Create: `frontend/src/api/account.js`
- Create: `frontend/src/api/__tests__/account.test.js` （如 vitest 配置允许）

**步骤:**

- [ ] **Step 1: 探查前端 axios 现状**

```bash
cd frontend
ls src/api/ 2>/dev/null
cat src/main.js 2>/dev/null | head -40
cat src/api/*.js 2>/dev/null | head -50
```

找到现有 axios 实例（如果有），复用；没有则新建。

- [ ] **Step 2: 写 account.js**

`frontend/src/api/account.js`：

```js
/**
 * Sub-Project 1: 用户与持仓 API 封装
 * 所有请求都带 withCredentials 让 cookie 自动收发
 */
import axios from "axios";

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || "",
  withCredentials: true,
  timeout: 15000,
});

export async function login(password) {
  const { data } = await http.post("/api/v1/auth/login", { password });
  return data;
}

export async function logout() {
  const { data } = await http.post("/api/v1/auth/logout");
  return data;
}

export async function switchUser(userId) {
  const { data } = await http.post("/api/v1/auth/switch-user", { user_id: userId });
  return data;
}

export async function whoami() {
  const { data } = await http.get("/api/v1/auth/whoami");
  return data;
}

export async function listUsers() {
  const { data } = await http.get("/api/v1/users");
  return data;
}

export async function listPortfolio() {
  const { data } = await http.get("/api/v1/portfolio");
  return data;
}

export async function addPortfolio(tsCode) {
  const { data } = await http.post("/api/v1/portfolio", { ts_code: tsCode });
  return data;
}

export async function removePortfolio(tsCode) {
  const { data } = await http.delete(`/api/v1/portfolio/${encodeURIComponent(tsCode)}`);
  return data;
}

export async function searchStocks(q, limit = 10) {
  const { data } = await http.get("/api/v1/stocks/search", { params: { q, limit } });
  return data;
}

http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response && err.response.status === 401) {
      // 触发登录跳转
      window.dispatchEvent(new CustomEvent("account:unauthorized"));
    }
    return Promise.reject(err);
  }
);

export default http;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/account.js
git commit -m "feat(frontend): add account API client with cookie auth"
```

---

### Task 15: 前端 — LoginView

**Files:**
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/src/views/__tests__/LoginView.test.js`

**步骤:**

- [ ] **Step 1: 写 LoginView**

`frontend/src/views/LoginView.vue`：

```vue
<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2>清水投研 · 登录</h2>
      <p class="hint">输入主密码以访问个人化功能</p>
      <el-form @submit.prevent="onSubmit">
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="主密码"
            show-password
            autofocus
            data-testid="password-input"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button
          type="primary"
          :loading="loading"
          data-testid="login-button"
          @click="onSubmit"
        >
          登录
        </el-button>
        <p v-if="error" class="error" data-testid="error-text">{{ error }}</p>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import { login } from "@/api/account";

const router = useRouter();
const password = ref("");
const loading = ref(false);
const error = ref("");

async function onSubmit() {
  if (!password.value) {
    error.value = "请输入主密码";
    return;
  }
  error.value = "";
  loading.value = true;
  try {
    const data = await login(password.value);
    if (data.users && data.users.length === 1) {
      // 只有一个用户，直接切换
      await switchAndGo(data.users[0].user_id);
    } else {
      router.push("/select-identity");
    }
  } catch (e) {
    error.value = e?.response?.data?.detail || "登录失败";
  } finally {
    loading.value = false;
  }
}

async function switchAndGo(userId) {
  const { switchUser } = await import("@/api/account");
  await switchUser(userId);
  router.push("/portfolio");
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.login-card {
  width: 360px;
}
.hint {
  color: #999;
  font-size: 13px;
  margin-bottom: 16px;
}
.error {
  color: #f56c6c;
  margin-top: 12px;
  font-size: 13px;
}
</style>
```

- [ ] **Step 2: 手动验证（开发服务器）**

```bash
cd frontend
pnpm dev
# 浏览器打开 http://localhost:5173/login
# 输错密码 → 显示错误
# 输对密码（要后端 MASTER_PASSWORD 已配）→ 跳 /select-identity 或 /portfolio
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/LoginView.vue
git commit -m "feat(frontend): add LoginView"
```

---

### Task 16: 前端 — SelectIdentityView

**Files:**
- Create: `frontend/src/views/SelectIdentityView.vue`

**步骤:**

- [ ] **Step 1: 写 SelectIdentityView**

`frontend/src/views/SelectIdentityView.vue`：

```vue
<template>
  <div class="select-page">
    <el-card>
      <h2>选择身份</h2>
      <p class="hint">请选择本次会话使用的身份</p>
      <div v-if="loading">加载中…</div>
      <div v-else class="user-grid">
        <el-card
          v-for="u in users"
          :key="u.user_id"
          class="user-card"
          shadow="hover"
          @click="pick(u.user_id)"
        >
          <div class="avatar">{{ u.display_name.slice(0, 1) }}</div>
          <div class="name">{{ u.display_name }}</div>
          <div class="uid">@{{ u.user_id }}</div>
        </el-card>
      </div>
      <el-button text class="logout" @click="onLogout">退出登录</el-button>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listUsers, logout, switchUser } from "@/api/account";

const router = useRouter();
const users = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await listUsers();
    users.value = data.users || [];
  } catch (e) {
    if (e?.response?.status === 401) router.push("/login");
  } finally {
    loading.value = false;
  }
});

async function pick(userId) {
  await switchUser(userId);
  router.push("/portfolio");
}

async function onLogout() {
  await logout();
  router.push("/login");
}
</script>

<style scoped>
.select-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.user-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.user-card {
  cursor: pointer;
  text-align: center;
}
.avatar {
  font-size: 28px;
  font-weight: 600;
  color: #409eff;
}
.name {
  margin-top: 8px;
  font-weight: 500;
}
.uid {
  font-size: 12px;
  color: #999;
}
.logout {
  margin-top: 24px;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/SelectIdentityView.vue
git commit -m "feat(frontend): add SelectIdentityView"
```

---

### Task 17: 前端 — PortfolioView

**Files:**
- Create: `frontend/src/views/PortfolioView.vue`

**步骤:**

- [ ] **Step 1: 写 PortfolioView**

`frontend/src/views/PortfolioView.vue`：

```vue
<template>
  <div class="portfolio-page">
    <el-card>
      <div class="header">
        <h2>我的持仓</h2>
        <div class="header-right">
          <span class="user-tag">@{{ currentUserId }}</span>
          <el-button text @click="goSwitch">切换身份</el-button>
          <el-button text @click="onLogout">退出</el-button>
        </div>
      </div>

      <el-autocomplete
        v-model="searchText"
        :fetch-suggestions="onSearch"
        placeholder="搜索股票代码或名称"
        :trigger-on-focus="true"
        :debounce="300"
        clearable
        class="search"
        @select="onSelect"
        data-testid="stock-search"
      >
        <template #default="{ item }">
          <div class="search-item">
            <span class="ts">{{ item.ts_code }}</span>
            <span class="name">{{ item.name }}</span>
            <span class="ind">{{ item.industry || "" }}</span>
          </div>
        </template>
      </el-autocomplete>
      <el-button
        type="primary"
        :disabled="!pendingAdd"
        data-testid="add-button"
        @click="confirmAdd"
      >
        加入持仓
      </el-button>

      <el-divider />

      <el-table :data="positions" v-loading="loading" empty-text="还没有持仓，搜索添加第一只">
        <el-table-column prop="ts_code" label="代码" width="120" />
        <el-table-column prop="stock_name" label="名称" />
        <el-table-column prop="created_at" label="加入时间" width="200">
          <template #default="{ row }">
            {{ new Date(row.created_at).toLocaleString() }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="right">
          <template #default="{ row }">
            <el-button
              type="danger"
              text
              data-testid="remove-button"
              @click="confirmRemove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  addPortfolio,
  listPortfolio,
  logout,
  removePortfolio,
  searchStocks,
  whoami,
} from "@/api/account";

const router = useRouter();
const positions = ref([]);
const loading = ref(false);
const searchText = ref("");
const pendingAdd = ref(null); // 选中的候选项
const currentUserId = ref("");

async function refreshUser() {
  const me = await whoami();
  currentUserId.value = me.user?.user_id || "";
  if (!currentUserId.value) {
    router.push("/select-identity");
  }
}

async function refresh() {
  loading.value = true;
  try {
    const data = await listPortfolio();
    positions.value = data.positions || [];
  } finally {
    loading.value = false;
  }
}

async function onSearch(queryString, cb) {
  try {
    const data = await searchStocks(queryString || "", 10);
    const items = (data.items || []).map((i) => ({
      value: `${i.ts_code} ${i.name}`,
      ...i,
    }));
    cb(items);
  } catch {
    cb([]);
  }
}

function onSelect(item) {
  pendingAdd.value = item;
  searchText.value = `${item.ts_code} ${item.name}`;
}

async function confirmAdd() {
  if (!pendingAdd.value) return;
  try {
    await addPortfolio(pendingAdd.value.ts_code);
    ElMessage.success(`已加入 ${pendingAdd.value.name}`);
    pendingAdd.value = null;
    searchText.value = "";
    await refresh();
  } catch (e) {
    const code = e?.response?.status;
    if (code === 409) ElMessage.warning("已在持仓中");
    else if (code === 422) ElMessage.error("股票代码无效");
    else ElMessage.error("添加失败");
  }
}

async function confirmRemove(row) {
  try {
    await ElMessageBox.confirm(`确定删除 ${row.stock_name}?`, "提示", { type: "warning" });
    await removePortfolio(row.ts_code);
    ElMessage.success("已删除");
    await refresh();
  } catch (e) {
    if (e === "cancel") return;
    ElMessage.error("删除失败");
  }
}

function goSwitch() {
  router.push("/select-identity");
}

async function onLogout() {
  await logout();
  router.push("/login");
}

onMounted(async () => {
  await refreshUser();
  await refresh();
});

// 监听全局 401 事件
window.addEventListener("account:unauthorized", () => {
  router.push("/login");
});
</script>

<style scoped>
.portfolio-page {
  padding: 24px;
  min-height: 100vh;
  background: #f5f7fa;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-right {
  display: flex;
  gap: 12px;
  align-items: center;
}
.user-tag {
  color: #999;
  font-size: 13px;
}
.search {
  width: 320px;
  margin-right: 8px;
}
.search-item {
  display: flex;
  gap: 12px;
  font-size: 13px;
}
.search-item .ts {
  font-weight: 600;
  color: #409eff;
}
.search-item .ind {
  color: #999;
  margin-left: auto;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/PortfolioView.vue
git commit -m "feat(frontend): add PortfolioView with search/add/remove"
```

---

### Task 18: 前端 — 路由 + 守卫

**Files:**
- Modify: `frontend/src/router/index.js`

**步骤:**

- [ ] **Step 1: 读现有路由配置**

```bash
cd frontend
cat src/router/index.js
```

记录现有路由结构。

- [ ] **Step 2: 加新路由 + 守卫**

在路由数组中追加：

```js
const routes = [
  // 既有路由 ...
  { path: "/", redirect: "/portfolio" },
  {
    path: "/login",
    name: "Login",
    component: () => import("@/views/LoginView.vue"),
    meta: { public: true },
  },
  {
    path: "/select-identity",
    name: "SelectIdentity",
    component: () => import("@/views/SelectIdentityView.vue"),
    meta: { requiresAuth: true, requiresUser: false },
  },
  {
    path: "/portfolio",
    name: "Portfolio",
    component: () => import("@/views/PortfolioView.vue"),
    meta: { requiresAuth: true, requiresUser: true },
  },
];
```

在 `router.beforeEach` 加：

```js
import { whoami } from "@/api/account";

router.beforeEach(async (to) => {
  if (to.meta.public) return true;
  try {
    const me = await whoami();
    if (!me) return { path: "/login" };
    if (to.meta.requiresUser && !me.user) {
      return { path: "/select-identity" };
    }
    return true;
  } catch (e) {
    if (e?.response?.status === 401) return { path: "/login" };
    return { path: "/login" };
  }
});
```

- [ ] **Step 3: 在 App.vue / main.js 增加菜单入口**

在侧边栏加：

```vue
<el-menu-item index="/portfolio" :route="{ name: 'Portfolio' }">我的持仓</el-menu-item>
```

（具体位置按现有 App.vue 结构插入）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router/index.js frontend/src/App.vue frontend/src/main.js
git commit -m "feat(frontend): wire account routes and global auth guard"
```

---

### Task 19: 端到端冒烟测试 + 文档

**Files:**
- Modify: `README.md`

**步骤:**

- [ ] **Step 1: 启动后端**

```bash
cd backend
source .venv/bin/activate
MASTER_PASSWORD=test-pass-1234 python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
# 等到看到 "已同步 2 个用户: [...]"
```

- [ ] **Step 2: 用 curl 走通完整流程**

```bash
# 1. 登录
curl -s -c /tmp/cookies.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"test-pass-1234"}' | python -m json.tool

# 2. 选身份
curl -s -b /tmp/cookies.txt -c /tmp/cookies.txt -X POST http://localhost:8000/api/v1/auth/switch-user \
  -H "Content-Type: application/json" \
  -d '{"user_id":"lwm"}' | python -m json.tool

# 3. 查持仓（空）
curl -s -b /tmp/cookies.txt http://localhost:8000/api/v1/portfolio | python -m json.tool

# 4. 搜索
curl -s -b /tmp/cookies.txt "http://localhost:8000/api/v1/stocks/search?q=茅台" | python -m json.tool

# 5. 加持仓
curl -s -b /tmp/cookies.txt -c /tmp/cookies.txt -X POST http://localhost:8000/api/v1/portfolio \
  -H "Content-Type: application/json" \
  -d '{"ts_code":"600519.SH"}' | python -m json.tool

# 6. 重复加（应 409）
curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/cookies.txt -X POST http://localhost:8000/api/v1/portfolio \
  -H "Content-Type: application/json" \
  -d '{"ts_code":"600519.SH"}'
# 预期: 409

# 7. 切到 partner_a 看不到
curl -s -b /tmp/cookies.txt -c /tmp/cookies.txt -X POST http://localhost:8000/api/v1/auth/switch-user \
  -H "Content-Type: application/json" \
  -d '{"user_id":"partner_a"}' > /dev/null
curl -s -b /tmp/cookies.txt http://localhost:8000/api/v1/portfolio
# 预期: {"positions":[]}

# 8. 退出
curl -s -b /tmp/cookies.txt -c /tmp/cookies.txt -X POST http://localhost:8000/api/v1/auth/logout
# 9. whoami 应 401
curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/cookies.txt http://localhost:8000/api/v1/auth/whoami
# 预期: 401
```

- [ ] **Step 3: 启动前端手测**

```bash
cd frontend
pnpm dev
# 浏览器:
# 1. 访问 http://localhost:5173 → 自动跳 /login
# 2. 输错密码 → 错误提示
# 3. 输对密码 → 跳 /select-identity
# 4. 选 "老王" → 跳 /portfolio
# 5. 搜索 "600519" 或 "茅台" → 选 → 加入持仓
# 6. 删除持仓
# 7. 切换身份 → 看不到刚才加的
# 8. 退出 → 跳 /login
```

- [ ] **Step 4: 在 README.md 增加"用户与持仓"小节**

在 README 适当位置追加：

```markdown
## 用户与持仓（Sub-Project 1）

系统支持多用户身份管理。每个用户可以维护自己的"持仓"列表（类似同花顺持仓栏的极简版）。

### 启用

1. 在 `backend/.env` 中设置 `MASTER_PASSWORD`（长度 ≥ 8）
2. 在 `backend/users.yaml` 中列出用户：
   ```yaml
   users:
     - user_id: lwm
       display_name: 老王
   ```
3. 重启后端。启动日志会打印"已同步 N 个用户"

### 使用

- 访问 `http://<host>:5173/login`，输入主密码
- 多个用户时选择身份，单个用户时直接进持仓
- 持仓页支持搜索/添加/删除；用户之间严格隔离
```

- [ ] **Step 5: 跑完整测试套件**

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -q
# 预期: 全部通过

cd ../frontend
pnpm test
# 预期: 全部通过（如有测试）
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: add 用户与持仓 section to README"
```

---

## 3. 自检（self-review）

1. **Spec 覆盖**
   - §4 包结构 → Task 4-12 实现 ✓
   - §5 数据模型 → Task 2-3 实现 ✓
   - §6 鉴权双轨 → Task 6, 8 实现，§6.1 保留 API Key 已在 main.py（既有代码）✓
   - §7 API 表面 → Task 11, 12 全部实现 ✓
   - §8 配置 → Task 1 实现 ✓
   - §9 前端 → Task 14-18 实现 ✓
   - §10 数据隔离 → Task 7, 12 测试覆盖 ✓
   - §11 测试 → 每个 service/api task 都有单测/集成测 ✓
   - §12 风险与缓解 → 文档已说明（启动校验、HttpOnly cookie）
   - §13 实施阶段 → 本 plan 即落地 ✓
   - §14 与后续子项目关系 → 不在本 plan 范围 ✓

2. **占位符扫描**
   - 全文无 TBD/TODO/待定/FIXME ✓
   - 错误码和路由都已具体到方法+路径 ✓
   - 测试代码完整可运行 ✓

3. **类型一致性**
   - `User.user_id` / `PortfolioPosition.user_id` 在 models / service / API 全程统一 ✓
   - `verify_master_token` / `get_current_user` 在 deps.py 定义，Task 11/12 引用一致 ✓
   - `ts_code` 格式校验在 schemas 中（`NNN.NN`），portfolio service 不重复校验 ✓

4. **实现风险点**
   - 集成测试用 `sqlite+aiosqlite` 内存数据库，需要在 conftest 中**完全替换** `app.core.database` 的 engine 和 session；如遇 import 时序问题，把 fixtures 拆成 module-level 包装。
   - 前端 vitest 默认可能没有 DOM 跑通 `LoginView.test.js`，故本 plan 未强制前端单测，而是用手动 dev 验证代替。
   - Stock 表实际字段可能不叫 `name` 而是 `symbol`+`name`，Task 10 Step 1 必须先探查。
   - CORS 中间件需要确认 `allow_credentials=True` 已设置；如没，需在 main.py 调整（现有 main.py 已设）。
