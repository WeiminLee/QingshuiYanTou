# 信号概念模型重构设计规格（Spec）

**日期**：2026-07-15
**范围**：重新定义清水投研的信号本体——引入两层模型（Observation 观察 → Signal 信号），统一承接文本类线索（新闻/公告/互动易/研报）与市场行为类线索（板块放量/逆大盘），并重构现有 `app/signals` 实现。
**取代关系**：本 spec 修订 `2026-07-13-signal-layer-design.md` 的概念模型部分；该 spec 的前端交互（SignalRadar）、Agent 注入、传导边界等设计仍然有效，消费对象改为新的聚合信号层。
**性质**：设计规格，供 implementation plan → TDD 实现。

---

## 1. 问题与动机

现有信号层（2026-07-13 设计、已实现）审视结论：

| 问题 | 现状 |
|------|------|
| 概念混淆 | `signals` 表实际存的是"单条来源的一次关键词命中"——它是**观察**，不是投研意义上的**信号** |
| 市场行为无法表达 | `SourcePayload`（title/content/summary）是纯文本容器，板块放量、逆大盘等数值型线索没有入口 |
| 无交叉验证概念 | "互动易确认客户导入"+"三天后板块放量"指向同一主体时，系统无法把它们关联成一条更强的线索 |
| 两套抽取器并存 | `app/signals/extractor.py`（新）与 `knowledge/extraction/signal_extractor.py`（老，549 行）并行，老版结果只进 KG 索引不进 signals 表 |
| 无自动化闭环 | 只有手动 backfill API，公告/新闻落库不会自动产生信号 |
| 抽取质量弱 | polarity 几乎全部硬编码 positive；subject 用 `tags[0]` 或标题前 24 字猜测 |
| 生命周期缺失 | freshness_score 只有 100/50 两档；信号不会强化、衰减、过期 |

核心判断：**问题不在字段设计，而在本体层次。** 投研中"信号"的价值来自多个独立观察的汇聚（预期差开始被市场定价的特征时刻），单层模型天然表达不了这件事。

---

## 2. 概念模型

### 2.1 两层本体

```text
Observation（观察）—— 原子事实层
  "某来源在某时刻出现了某个值得注意的现象"
  - 文本观察：公告提到量产、互动易确认客户导入、新闻报道政策
  - 市场观察：光模块板块今日放量 2.3x、通信板块逆大盘上涨
  - 特点：一对一来源可追溯、机器批量产出、允许噪声、不直接面向用户

Signal（信号）—— 聚合判断层
  "围绕某主体、某方向，一条或多条观察构成的可下钻投研线索"
  - 双路径生成：高价值观察直升 / 多观察聚合（规则粗筛 + LLM 终判）
  - 活对象：可强化、可衰减、有生命周期
  - 前端 SignalRadar 与 Agent 上下文注入只消费这一层
```

### 2.2 观察 → 信号的双路径

**路径 A：直升（promote）**
单条观察满足直升条件（来源权威 + obs_type 高价值 + strength 超阈值，如公告类 `mass_production` / `order` / `earnings`），立即生成信号。观察 `status=promoted`，信号 `observation_count=1`。

**路径 B：聚合（aggregate）**
定时任务把时间窗口内未归属的观察按主体分组：

1. **规则粗筛**：同主体（归一化后）+ 时间窗口（默认 7 天）内 ≥2 条观察 → 形成候选簇。
2. **LLM 终判**：把候选簇（含各观察 summary/excerpt/metrics）与该主体现有 active 信号一起交给 LLM，输出结构化决策：
   - `merge_into_existing`：归入现有信号（强化）
   - `create_new`：新建信号，生成 title / thesis_summary / direction
   - `no_signal`：观察间无实质关联，保持 pending
3. LLM 判定同一信号的观察回填 `signal_id`，`status=attached`。

**去向兜底**：pending 观察超过保留期（默认 14 天）自动 `discarded`，不永久堆积。

### 2.3 信号生命周期（活信号）

```text
                    新观察归入（同方向）
        ┌──────────────────────────────────┐
        ▼                                  │
  active ──时间衰减──> weakened ──继续衰减──> expired
        │                                  
        ├─ 强验证观察（如公告证实）──> confirmed
        ├─ 矛盾观察（LLM 判定反向）──> refuted
        └─ 新观察强化 ──> strengthened（strength/value_score 上调，回到 active 态计时）
```

- **强化**：新观察归入时，strength 按增量提升，`last_reinforced_at` 刷新，`source_diversity` 重算。
- **衰减**：每日任务按 `last_reinforced_at` 距今天数衰减 strength（半衰期按 signal_type 配置：政策类慢、行情类快）。降到阈值以下 → `weakened`；再降 → `expired`。
- **confirmed / refuted**：由 LLM 聚合终判时一并判定（新观察与现有信号的关系：strengthen / contradict / confirm）。
- `lifecycle` 与用户侧 `status`（new/viewed/dismissed…）正交，互不干扰。

---

## 3. 数据模型

### 3.1 `observations`（新表）

```text
observations
- id BIGSERIAL PK
- observation_id VARCHAR(40) UNIQUE NOT NULL      -- "OBS:" + sha256(...)[:20]
- obs_class VARCHAR(16) NOT NULL                  -- text | market
- source_type VARCHAR(32) NOT NULL                -- announcement/news/irm/research_report/market_metric
- source_id VARCHAR(128) NOT NULL                 -- event_id/evidence_id/指标快照ID
- source_title TEXT
- source_url TEXT
- subject_name TEXT NOT NULL
- subject_type VARCHAR(32) NOT NULL               -- company/product/sector/concept/policy/macro
- obs_type VARCHAR(64) NOT NULL                   -- 文本类沿用现有7类 + 市场类新增3类
- polarity VARCHAR(16) NOT NULL
- strength INTEGER NOT NULL                       -- 0-100
- confidence NUMERIC(4,3) NOT NULL
- summary TEXT NOT NULL
- evidence_excerpt TEXT                           -- 文本类=原文句子；市场类=数值快照描述
- observed_at TIMESTAMPTZ NOT NULL                -- 文本类=published_at；市场类=检测时刻
- window VARCHAR(16)                              -- 市场类专用：intraday/daily
- metrics JSONB NOT NULL DEFAULT '{}'             -- 市场类原始数值：量比/涨幅/相对大盘超额
- signal_id VARCHAR(40) REFERENCES signals(signal_id) ON DELETE SET NULL
- status VARCHAR(16) NOT NULL DEFAULT 'pending'   -- pending/attached/promoted/discarded
- metadata JSONB NOT NULL DEFAULT '{}'
- created_at / updated_at TIMESTAMPTZ
```

稳定 ID：`OBS: + sha256(source_type|source_id|normalized_subject|obs_type|normalized_excerpt[:120])[:20]`（沿用现有 `stable_signal_id` 逻辑改前缀）。

obs_type 全集（第一版）：

| 类别 | obs_type |
|------|----------|
| 文本类（沿用） | mass_production / capacity / policy / capex / earnings / order / risk |
| 市场类（新增） | volume_surge（板块放量）/ counter_market（逆大盘）/ sector_momentum（板块连续走强） |

索引：`(subject_type, subject_name, observed_at)`、`(status)`、`(source_type, source_id)`、`(signal_id)`。

### 3.2 `signals`（重建语义：聚合层）

```text
signals
- id BIGSERIAL PK
- signal_id VARCHAR(40) UNIQUE NOT NULL           -- "SIG:" + sha256(subject|type|首观察id)[:20]
- subject_name TEXT NOT NULL
- subject_type VARCHAR(32) NOT NULL
- signal_type VARCHAR(64) NOT NULL                -- 主导观察的 obs_type
- direction VARCHAR(16) NOT NULL                  -- positive/negative/risk/mixed
- title TEXT NOT NULL                             -- LLM 生成（直升路径用规则模板）
- thesis_summary TEXT NOT NULL                    -- 为什么值得关注（LLM 生成/模板）
- strength INTEGER NOT NULL                       -- 当前强度，随强化/衰减变动
- confidence NUMERIC(4,3) NOT NULL
- value_score INTEGER NOT NULL                    -- 排序分
- observation_count INTEGER NOT NULL DEFAULT 1
- source_diversity INTEGER NOT NULL DEFAULT 1     -- 独立 source_type 数
- lifecycle VARCHAR(24) NOT NULL DEFAULT 'active' -- active/strengthened/weakened/confirmed/refuted/expired
- first_observed_at TIMESTAMPTZ NOT NULL
- last_reinforced_at TIMESTAMPTZ NOT NULL
- expires_at TIMESTAMPTZ                          -- 衰减任务维护
- status VARCHAR(24) NOT NULL DEFAULT 'new'       -- 用户侧：new/viewed/reviewed/dismissed/archived
- metadata JSONB NOT NULL DEFAULT '{}'            -- portfolio_hits 等
- created_at / updated_at TIMESTAMPTZ
```

索引：`(value_score DESC, last_reinforced_at DESC)`、`(subject_type, subject_name)`、`(lifecycle)`、`(status)`、GIN(metadata)。

### 3.3 `signal_propagations`（保留）

结构不变，外键挂到新 signals。第一版仍是轻量模板传导；接 Neo4j 真图谱传导另立项。

### 3.4 迁移策略

现有 signals 表数据全部为规则抽取的低质量数据，**不迁移**。Alembic 迁移：drop 旧 signals/signal_propagations → 建新三表。前端与 API 同步切换。

---

## 4. 观察产出管线

### 4.1 文本观察（重构现有）

统一入口 `app/signals/observers/text.py`，输入沿用 `SourcePayload`，输出 `ObservationCandidate`。

抽取器整合：

- 合并 `knowledge/extraction/signal_extractor.py`（549 行老版）与 `app/signals/extractor.py`（新版）为一套规则抽取器，关键词集取并集，去掉老版；`evidence_worker` / `kg_extractor` 改为调用新入口（其 KG 索引所需的 signals 字段从观察结果适配）。
- **polarity 修正**：关键词分正负两组（如 earnings 类："预增/超预期" → positive，"不及预期/低于预期" → negative；order 类："中标/大额订单" → positive，"订单延期/取消" → negative），不再按 obs_type 硬编码。
- **subject 修正**：优先级 metadata.ts_code/公司名（公告/互动易自带）> metadata.tags > LLM 兜底（可选）> 标题截断（最后手段，confidence 打折）。

触发（落库 hook）：

- **公告/互动易/研报**：`evidence_worker.process_job` 处理完 Evidence 后同步调用观察抽取（同事务外、失败不阻塞主流程，记日志）。
- **新闻**：events 落库管线（`event_ingestion` 现有 backfill 改造为 hook + 保留手动 backfill 兜底）。

### 4.2 市场观察（新增）

`app/signals/observers/market.py`，第一版只做**板块/概念级**，数据源为现有 `ConceptLimit` 等板块日频表（`concept_service` 已有查询能力）。

检测规则（盘后定时任务，交易日收盘后执行一次）：

| obs_type | 触发条件（默认参数，可配置） |
|----------|------------------------------|
| volume_surge | 板块当日成交额 / 近20日均值 ≥ 1.8，且板块涨跌幅绝对值 ≥ 2% |
| counter_market | 大盘跌 ≥ 0.5% 且板块涨 ≥ 1%（或反向） |
| sector_momentum | 板块连续 ≥3 个交易日跑赢大盘，累计超额 ≥ 5% |

产出规范：

- `subject_type=concept/sector`，`subject_name` 使用板块表的标准名称（天然归一，无需额外处理）。
- `metrics` 存原始数值，`evidence_excerpt` 生成人读描述（"量比2.3，板块+3.1%，大盘-0.8%"）。
- 同板块同 obs_type 同交易日的观察由稳定 ID 天然去重。
- 市场观察 strength 按偏离度线性映射（如量比 1.8→60 分，3.0→90 分）。

**市场观察不走直升路径**——单日板块异动噪声大，只作为聚合路径的验证性观察参与信号形成/强化。

### 4.3 主体归一

聚合的分组键是主体，跨来源主体写法不一（"中际旭创" vs "300308.SZ"；"光模块" vs "CPO概念"）。第一版策略：

- company：统一归一为 ts_code（公告/互动易自带；新闻文本用现有股票表名称匹配）。
- sector/concept：以板块表标准名为准；文本观察的概念词用别名表映射（第一版手工维护核心板块别名，未命中保持原名）。
- 归一失败不阻塞：保持原 subject_name，只是失去跨来源聚合机会。

---

## 5. 聚合引擎

`app/signals/aggregator.py`，定时任务驱动（默认每小时一次 + 盘后市场观察产出完成后追加一次）。

### 5.1 流程

```text
1. 取 status=pending 的观察
2. 直升判定：命中直升规则的观察 → 立即建信号（模板 title），status=promoted
3. 剩余按归一化主体分组，窗口默认 7 天
4. ≥2 条观察的组 → 候选簇进入 LLM 终判
5. LLM 输入：候选簇观察列表 + 该主体现有 active/strengthened/weakened 信号摘要
   LLM 输出（结构化）：
   [
     {action: merge_into_existing, signal_id, relation: strengthen|contradict|confirm,
      observation_ids: [...]},
     {action: create_new, title, thesis_summary, direction, observation_ids: [...]},
     {action: no_signal, observation_ids: [...]}
   ]
6. 执行：建信号/归属观察/更新 lifecycle 与 strength/source_diversity/last_reinforced_at
7. LLM 失败降级：候选簇保持 pending，下轮重试；连续失败告警日志
```

### 5.2 直升规则（第一版）

```text
可直升 source_type：announcement / irm / research_report（evidence 系）
可直升 obs_type：mass_production / order / earnings / risk
条件：strength ≥ 75 且 confidence ≥ 0.7
news 与 market_metric 一律不直升
```

### 5.3 评分

```text
value_score =
  base(主导 obs_type 权重)
  + strength_weight(当前 strength)
  + diversity_boost(source_diversity ≥ 2 显著加分，文本+市场交叉命中额外加分)
  + freshness(按 last_reinforced_at 衰减)
  + portfolio_boost(命中用户持仓/关注)
  - noise_penalty
```

风险信号不降分（沿用 07-13 spec 原则）。

### 5.4 衰减任务

每日一次：按 signal_type 配置半衰期（政策类 30 天、业绩/订单类 14 天、行情驱动类 5 天），对 `last_reinforced_at` 距今超期的信号执行 strength 衰减与 lifecycle 降级（active→weakened→expired）。expired 信号不再进入前端默认列表与 Agent 注入。

---

## 6. 消费层适配

### 6.1 API

沿用 07-13 spec 的三个端点，语义升级：

- `GET /api/v1/signals`：返回聚合信号，新增字段 `observation_count` / `source_diversity` / `lifecycle` / `thesis_summary`；新增过滤参数 `lifecycle`。
- `GET /api/v1/signals/{id}`：详情新增 `observations` 数组（每条观察的来源、时间、摘要、原文锚点），替代原单一 `evidence_excerpt`。
- `POST /api/v1/signals/{id}/status`：不变。
- 手动 backfill 端点保留（运维兜底），新增 `POST /api/v1/signals/aggregate/run`（手动触发一轮聚合，调试用）。

### 6.2 Agent 注入

`context_provider.py` 格式升级：

```text
<signal-context>
[高价值信号] 800G 光模块量产确认，板块资金开始响应
  signal_id / value_score / confidence / lifecycle: strengthened
  线索: (thesis_summary)
  观察链:
  - [公告 07-10] 公司公告 800G 光模块进入规模量产（原文锚点…）
  - [互动易 07-12] 确认已向北美大客户批量交付
  - [行情 07-14] 光模块板块放量 2.3x，逆大盘上涨
  传导: …（沿用）
  相关持仓: …（沿用）
</signal-context>
```

观察链是两层模型给 Agent 的核心增量——Agent 能看到线索的证据结构而非孤立句子。

### 6.3 前端 SignalRadar

组件保留，卡片增量展示：`observation_count`（"3 条观察"徽标）、`source_diversity ≥ 2` 时展示"交叉验证"标记、lifecycle 标签（strengthened 高亮）。轻量详情抽屉展示观察链列表。交互（hover 暂停、问 Agent、signal_id 透传）全部沿用。

---

## 7. 模块结构

```text
backend/app/signals/
├── models.py                  # Observation / Signal / SignalPropagation ORM
├── schemas.py                 # API schema
├── observers/
│   ├── __init__.py
│   ├── text.py                # 文本观察抽取（合并两套规则抽取器）
│   └── market.py              # 板块级市场观察检测
├── subject_norm.py            # 主体归一（ts_code / 板块别名表）
├── aggregator.py              # 直升 + 规则粗筛 + LLM 终判
├── lifecycle.py               # 强化/衰减/过期
├── ingestion.py               # 落库 hook 入口 + backfill（合并现有两个 ingestion 文件）
├── propagation.py             # 轻量传导（保留）
├── context_provider.py        # Agent 注入（升级观察链格式）
├── service.py                 # 查询服务
└── api.py                     # API 路由
删除：knowledge/extraction/signal_extractor.py（规则并入 observers/text.py）
```

调度接线（`data_pipeline/scheduler.py`）：

| 任务 | 频率 |
|------|------|
| 市场观察检测 | 交易日盘后一次 |
| 聚合引擎 | 每小时 + 盘后市场观察完成后追加 |
| 衰减任务 | 每日一次 |
| pending 观察清理 | 每日一次 |

---

## 8. 测试策略

单元测试：

- 观察稳定 ID 幂等；文本抽取 polarity 正负分组正确（"订单延期"→negative）。
- subject 归一：ts_code 优先、板块别名映射、未命中保原名。
- 市场观察三条规则在构造数据下的触发/不触发边界。
- 直升规则：announcement+order+高分直升；news/market 不直升。
- 聚合粗筛分组：同主体窗口内成簇、跨主体不混。
- LLM 终判 mock：merge/create/no_signal 三分支的执行正确性；LLM 失败降级 pending。
- 生命周期：强化刷新 last_reinforced_at 与 diversity；衰减降级链 active→weakened→expired；confirmed/refuted 转移。
- value_score：diversity_boost 与交叉命中加分的排序影响。

集成测试：

- 公告 Evidence → 观察 → 直升信号全链路。
- 新闻 + 行情观察 → 聚合成单一信号，source_diversity=2。
- API 列表/详情返回观察链；Agent 注入含观察链格式。

前端测试：观察数徽标、交叉验证标记、lifecycle 标签渲染；其余沿用现有 SignalRadar 测试。

---

## 9. 成功标准

1. 四类来源（新闻、公告、互动易、板块行情）都能产生观察并进入同一聚合层。
2. "互动易表态 + 三天后板块放量"能聚合为一条 source_diversity=2 的信号，且 value_score 高于任一单独观察直升的信号。
3. 公告落库后无需人工触发即产生观察；盘后自动产生市场观察。
4. 信号随新观察强化、随时间衰减，expired 信号退出默认列表。
5. Agent 注入上下文包含观察链，能区分"单一来源线索"与"交叉验证线索"。
6. 系统内只剩一套文本抽取规则。
7. 信号层仍不写入买卖结论（沿用 07-13 边界）。

---

## 10. 分阶段实施建议

### Phase 1：数据模型与观察层
- Alembic：drop 旧表、建 observations + 新 signals + propagations。
- 合并两套文本抽取器 → observers/text.py（含 polarity/subject 修正）。
- subject_norm 第一版。
- evidence_worker / events 落库 hook。

### Phase 2：市场观察 + 聚合引擎
- observers/market.py 板块级三规则。
- aggregator：直升 + 粗筛 + LLM 终判 + 降级。
- 调度接线四个定时任务。

### Phase 3：生命周期与评分
- lifecycle 强化/衰减/过期。
- value_score 新公式（diversity_boost）。

### Phase 4：消费层
- API/service 升级（观察链）。
- context_provider 观察链格式。
- SignalRadar 增量展示。

---

*Spec 结束。下一步：用户复审本 spec 后，进入 implementation plan。*
