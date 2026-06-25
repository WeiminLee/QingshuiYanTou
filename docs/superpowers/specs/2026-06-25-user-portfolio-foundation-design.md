# Sub-Project 1: 用户与持仓基础（User & Portfolio Foundation）

> 日期：2026-06-25
> 状态：Approved（待用户复审）
> 范围：Sub-Project 1 / 3 之一
> 关联：Sub-Project 2（持仓跟踪与预警）、Sub-Project 3（预期事件订阅）

## 1. 背景与目标

### 1.1 现状

- 系统当前**没有用户体系**，所有数据共享一套 `API_KEY` 鉴权。
- 知识层、Agent 层、数据采集层都是面向"投研材料"的，**没有"个人"维度**。
- 现有 `verify_api_key` 仅用于管理类写操作（数据同步、Knowledge 写入），与"用户身份"无关。

### 1.2 目标

新增 Sub-Project 1 作为后续子项目（2、3）的基础：

- **多用户身份**：系统支持多个注册用户，每人拥有独立的"持仓"。
- **持仓管理**：每个用户可手动添加/删除持仓股票（类似同花顺"持仓"列表的极简版）。
- **统一鉴权**：在保留现有 `API_KEY`（管理通道）的同时，新增"主密码 + 切换身份"的用户态鉴权。
- **数据隔离**：用户之间持仓数据严格隔离。

### 1.3 非目标（不在本子项目范围）

- 交易流水、已实现盈亏、成本价/数量管理（简化版不做）
- 真实券商接口（保持手工录入）
- 持仓跟踪、预警、通知（属于 Sub-Project 2）
- 预期事件订阅（属于 Sub-Project 3）
- 邮箱/手机号/验证码/OAuth（自部署场景不需要）
- 港美股（仅 A 股，与现有数据源范围一致）
- 持仓分组、标签、备注

## 2. 设计原则

| 原则 | 落地 |
|------|------|
| 简单优先 | 主密码 + 切换身份，无注册流程，无密码重置 |
| 配置驱动 | 用户列表放 yaml，不在 UI 创建 |
| 双轨鉴权 | API Key 走管理，master_token 走用户态，**并存不冲突** |
| 数据隔离 | 任何 `account_*` 查询必须走 service 层并带 `user_id` |
| 向前兼容 | Sub-Project 2、3 能直接复用本子项目的 user/portfolio 概念 |

## 3. 部署形态

- 单实例 Docker Compose
- 用户量 ≤ 几十人（小圈子自部署）
- 主密码从环境变量读取，启动时 hash 进内存

## 4. 包结构

新增独立子包 `app/account/`，与 `app/data_pipeline/`、`app/knowledge/`、`app/reasoning/` 平级：

```
backend/app/account/
├── __init__.py
├── config.py                  # 读 MASTER_PASSWORD / users.yaml
├── models.py                  # User / PortfolioPosition (SQLAlchemy)
├── schemas.py                 # Pydantic 请求/响应模型
├── services/
│   ├── __init__.py
│   ├── user_service.py        # 用户加载/yaml 同步
│   ├── auth_service.py        # 主密码校验、token 签发/校验
│   └── portfolio_service.py   # 持仓增删查
├── api/
│   ├── __init__.py
│   ├── auth.py                # /api/v1/auth/*
│   ├── users.py               # /api/v1/users
│   └── portfolio.py           # /api/v1/portfolio
├── deps.py                    # FastAPI Depends: get_current_user, verify_master_token
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_auth.py
    ├── test_user_service.py
    └── test_portfolio.py
```

## 5. 数据模型

### 5.1 表结构

**users**（启动时由 `users.yaml` 同步到 DB，运行期只读）

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | VARCHAR(64) PK | 主键，与 yaml 对应 |
| `display_name` | VARCHAR(128) | 显示名（"老王"） |
| `is_active` | BOOLEAN | 默认 true；yaml 删除用户时置 false 而非真删 |
| `created_at` | TIMESTAMPTZ | 首次同步时间 |
| `updated_at` | TIMESTAMPTZ | 最后同步时间 |

**portfolio_positions**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | 自增 |
| `user_id` | VARCHAR(64) FK→users | 所属用户 |
| `ts_code` | VARCHAR(16) | 股票代码（`600519.SH` 格式） |
| `stock_name` | VARCHAR(64) | 股票名称（冗余缓存，便于列表展示） |
| `created_at` | TIMESTAMPTZ | 加入持仓时间 |
| `UNIQUE` | `(user_id, ts_code)` | 同一只股票不能重复添加 |

### 5.2 迁移

新增 alembic 迁移：`YYYY_add_account_tables.py`

- 创建 `users`、`portfolio_positions` 两张表
- 不需要数据回填（新表，初始为空）

## 6. 鉴权设计

### 6.1 双轨制

| 通道 | 用途 | 既有/新增 | 校验方式 |
|------|------|----------|----------|
| `API_KEY` | 管理类写操作（数据同步、Knowledge 写入） | 既有 | Header `X-API-Key` |
| `master_token` | 用户态接口（持仓、用户切换、未来的预警/订阅） | 新增 | HttpOnly+Secure+SameSite=Lax Cookie `master_token` |
| `user_id` | 当前激活身份 | 新增 | 普通 Cookie `user_id`（不敏感） |

### 6.2 Token 设计

- 算法：HS256 JWT
- Payload：`{ "exp": ..., "iat": ..., "type": "master" }`
- 签名密钥：启动时由 `MASTER_PASSWORD` + 服务端 salt 派生（不存 DB）
- 过期：永不过期（自部署场景，做"软过期"机制留待 v2）

### 6.3 依赖注入

```python
# app/account/deps.py
async def get_current_user(request: Request) -> User:
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(401, "未选择身份")
    user = await user_service.get_active(user_id)
    if not user:
        raise HTTPException(401, "身份无效或已停用")
    return user

async def verify_master_token(request: Request) -> None:
    token = request.cookies.get("master_token")
    if not token or not auth_service.verify_token(token):
        raise HTTPException(401, "未登录或会话失效")
```

## 7. API 表面

| 路由 | 方法 | 鉴权 | 请求 | 响应 |
|------|------|------|------|------|
| `/api/v1/auth/login` | POST | 无 | `{password: str}` | `{ok: true}` + Set-Cookie |
| `/api/v1/auth/logout` | POST | master_token | — | `{ok: true}` + 清 cookie |
| `/api/v1/auth/switch-user` | POST | master_token | `{user_id: str}` | `{ok: true, current_user: User}` + Set-Cookie |
| `/api/v1/auth/whoami` | GET | master_token | — | `{user: User\|null, users: [User]}`（前端启动时调用，决定展示登录页 or 切换器） |
| `/api/v1/users` | GET | master_token | — | `[{user_id, display_name}, ...]` |
| `/api/v1/portfolio` | GET | master_token + current_user | — | `[{ts_code, stock_name, created_at}, ...]` |
| `/api/v1/portfolio` | POST | master_token + current_user | `{ts_code: str}` | `{ok: true, position: Position}` |
| `/api/v1/portfolio/{ts_code}` | DELETE | master_token + current_user | — | `{ok: true}` |
| `/api/v1/stocks/search` | GET | master_token | `?q=贵州茅台&limit=10` | `[{ts_code, name, industry}, ...]` |

错误约定：

- 401：未登录 / 会话失效 → 前端跳登录页
- 403：已登录但 user_id 无效 → 重新选身份
- 404：资源不存在或不属于当前用户（避免泄漏存在性）
- 409：重复添加持仓
- 422：股票代码不存在 / 格式错误

## 8. 配置

### 8.1 `backend/.env`（新增）

```bash
MASTER_PASSWORD=your-strong-password
ACCOUNT_TOKEN_SECRET_SALT=auto-generated-if-missing  # 可选，默认走固定 dev salt
```

### 8.2 `backend/users.yaml`（新增）

```yaml
users:
  - user_id: lwm
    display_name: 老王
  - user_id: partner_a
    display_name: 合伙人甲
```

### 8.3 启动行为

- 应用 `lifespan` 中：
  1. 校验 `MASTER_PASSWORD` 必填且长度 ≥ 8
  2. 派生 token 签名密钥
  3. 调用 `user_service.sync_from_yaml()` 把 yaml 用户 upsert 到 DB
- 启动日志打印：`已同步 N 个用户: [lwm, partner_a]`

## 9. 前端集成（Vue 3）

### 9.1 新增路由

| 路径 | 组件 | 说明 |
|------|------|------|
| `/login` | `LoginView.vue` | 主密码输入页（仅一个输入框 + 登录按钮） |
| `/portfolio` | `PortfolioView.vue` | 我的持仓（需登录 + 选中身份） |
| `/select-identity` | `SelectIdentityView.vue` | 选中身份页（已登录但未选身份时出现） |
| `/` | 重定向 | 未登录 → `/login`；已登录未选身份 → `/select-identity`；已选身份 → `/portfolio` |

### 9.2 持仓页 UI 草图

```
┌─────────────────────────────────────────────────┐
│  我的持仓                       [切换身份: 老王 ▾] │
├─────────────────────────────────────────────────┤
│  [🔍 搜索股票代码或名称...]      [+]              │
├─────────────────────────────────────────────────┤
│  600519.SH  贵州茅台        2026-01-15  [删除]   │
│  300750.SZ  宁德时代        2026-03-20  [删除]   │
│  ...                                            │
└─────────────────────────────────────────────────┘
```

- 搜索框：输入 ≥ 1 字符触发 `/api/v1/stocks/search`，下拉显示前 10 条
- 选中候选 → 调 `/api/v1/portfolio POST`
- 列表每行调 `GET /api/v1/portfolio`（首次进入时拉一次）
- 删除按钮 → 二次确认弹窗 → 调 `DELETE`

### 9.3 全局鉴权守卫

- 路由 `beforeEach`：未登录访问受保护页 → 跳 `/login`
- 已登录但未选身份 → 跳 `/select-identity`
- 任何 401 响应 → 清 cookie + 跳 `/login`

## 10. 数据隔离

- `portfolio_service` 任何查询必须显式传 `user_id` 参数
- 单元测试覆盖：
  - 用用户 A 的 token 调 `DELETE /api/v1/portfolio/{B 的 ts_code}` → 404
  - 用 A 的 token `GET /api/v1/portfolio` 不返回 B 的持仓
  - 直接调 `portfolio_service.get(A_user, X_code)` 不会意外返回 A 没有的资源

## 11. 测试

| 类型 | 覆盖 |
|------|------|
| 单元 | `test_auth_service`（token 签发/校验/过期）、`test_user_service`（yaml 解析/同步）、`test_portfolio_service`（CRUD + 隔离） |
| 集成 | `test_auth_api`（login/logout/switch-user/whoami）、`test_portfolio_api`（增删查 + 401/403/404/409/422） |
| 前端 | vitest 单测：登录页校验、路由守卫、持仓列表渲染 |
| 手动 | docker compose up 后 5 分钟 smoke：登录 → 选身份 → 加 2 只股票 → 删除 1 只 → 切到另一用户 → 看不到 → 登出 |

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 主密码忘了 → 改 .env + 重启 | 自部署可接受；文档明示 |
| yaml 编辑出错导致启动失败 | 启动校验 schema，错误时 fail-fast |
| token 不做过期 → 泄露风险 | 自部署场景，文档明示"主密码即命门"，建议强密码 |
| 多浏览器同时用同一身份 | 不阻止；持仓是个人数据但不是机密，行为合理 |
| 后续 Sub-Project 2 需要"成本价"等扩展 | 数据模型预留：可在 `portfolio_positions` 加 nullable 列，或新建 `transactions` 表聚合 |

## 13. 实施阶段（高层级，详细计划交给 writing-plans）

1. 后端：包结构 + 模型 + alembic 迁移 + service + api + deps + 测试
2. 前端：登录页 + 选中身份页 + 持仓页 + 路由守卫
3. 联调：docker compose up → 5 分钟 smoke
4. 文档：README 增加"用户与持仓"小节

预计：1 轮迭代（1-2 天）。

## 14. 与后续子项目的关系

- **Sub-Project 2（持仓跟踪与预警）** 复用 `User` 和 `PortfolioPosition`，新增 `PortfolioSnapshot`、`Alert` 等表
- **Sub-Project 3（预期事件订阅）** 复用 `User`，新增 `Event`、`Subscription` 等表，`User` 表可后续加 `telegram_id` 之类的可选字段
- 鉴权层（master_token + current_user）原样复用，不需改动
