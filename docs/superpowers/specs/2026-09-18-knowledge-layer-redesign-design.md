# 知识层重构设计：Evidence 链接层 + 判断台账（2026-09-18, v2）

> **状态**：设计稿 v2，待 owner 评审。
> **v2 修订**（吸收 09-18 讨论）：①批量侧引入 LLM 浅提取（类型受约束关键字提取），修订"零 LLM"为"浅任务"原则；②METRIC 提取带数值属性；③embedding 从辅助岗升级为与关键字并列的第一通道；④新增板块/概念/主题三层设计与三类查询原语；⑤新增单跳聚合工具族。
> **前置**：《预期差的理解与设想（2026-09-17）》《检索架构与预期差路线调研（2026-09-17）》《findings 判断台账设计草案 v0.1（2026-09-17）》。

---

## 0. 结论先行

| 决策 | 内容 |
|---|---|
| **摒弃** | 三元组批量 LLM 抽取管线（combined jobs）、Neo4j 写入、`kg_entities`/`kg_relations` 向量集合、`_compute_gap` |
| **新建** | 双通道链接层：**关键字通道**（LLM 浅提取 Company/Product/Metric + 词典匹配 dimension/stage）+ **向量通道**（dense，语义聚合与主题） |
| **承接** | 9-17 台账设计：observation / finding / watermark 落为 L2 判断层 |
| **调岗** | Embedding 与关键字并列第一通道：语义召回、变体归并、概念/板块/主题聚合 |
| **保持** | Evidence-first 边界（知识层只存事实不存结论）、kg_evidence 27.6 万条真源全部保留 |

---

## 1. 背景与动机

### 1.1 三元组管线的两个死因（实证）

1. **成本模型错误：无差别预付。** 275,689 条 evidence 中 91.4% 未抽取（251,951 条 pending），吞吐 ~1,800 条/天，清完需 ~217 天；已抽取部分**仅 ~3% 产出过任何实体/关系**。
2. **质量不可逆地烙死在库里。** 实体归一化、泛称公司名、裸值 Metric、关系类型误判——每个错误都写进 Neo4j，修复靠重跑全量。

死因的精确定位：**不是"用了 LLM"，而是输出复杂度（嵌套 JSON、重试链）和归一化负担（LLM 生成 canonical ID）**。类型受约束的浅提取两者皆无。

### 1.2 调研结论

- **PageIndex**：结构可以从版面/词典机械获得；它是单文档精读器，对平均 3,119 字符的公告/互动易不直接适用，但"结构零成本"思想全面吸收。
- **WikiLLM / Karpathy llm-wiki**：知识应"编译一次、持续维护"；但全量编译同样支付 LLM 成本，且 WiCER（arXiv:2605.07068）实证一次性盲编译 53–60% 灾难性丢事实——**有损编译步骤被整体否决**。
- **Agentic Search（09-17 阅读报告）**：Argus（互补性：相似性是无状态函数，互补性是状态函数，top-k 相似性采样对时间线有偏）；SearchAtlas（窄归因 + 硬证据闸门：0.860 vs 自由生成 0.072）；ITER（已消费降权）；HypoSearch（分歧后才分支，78% 失败是探索失败）；IBIS（干净上下文评判，-33% token）。

### 1.3 重构的本质

**把"无差别预付的深抽取"换成"廉价的浅提取 + 按需的深判断 + 判断结果的永久沉淀"。**

---

## 2. 核心设计原则

1. **原子不编译。** Evidence 是唯一真源（append-only）。任何结构（关键字、观察、判断）都是 evidence 之上的投影，可随时删除重算。没有有损编译步骤。
2. **批量侧只许浅任务。** 禁止的是深抽取（关系、结构化事实、多调用重试链）；允许的是浅提取：**单次调用、扁平输出、可缓存、可全量重算**。LLM 只做类型受约束的摘抄，不做推理、不改写、不归一。
3. **状态使能检索。** `value(e) ≈ Δ(知识状态, e)`。互补性检索以台账为前提：Argus 在检索层找拼图缺口，ITER 在排序层给已消费降权，水位线在判断层判新台阶——一条原理，三层实现。
4. **判断与事实分离（边界不变）。** 知识层不沉淀买卖结论；finding 是判断的记录，不是投资建议。

---

## 3. 总体架构

```
L3 服务层    Agent 工具面（pull / scan / browse / lookup / write_*） + SignalRadar
     │
L2 判断层    observation / finding / watermark      ← LLM 深判断唯一发生地（task-time）
     │
L1 链接层    关键字通道（sparse）+ 向量通道（dense）+ 词法检索
     │        浅 LLM + 词典 + embedding，全部可全量重算
     │
L0 证据层    kg_evidence（Mongo，append-only 真源，27.6 万条，全部保留）
```

数据流：

```
摄入（已有）   公告/互动易 → parse → chunk → kg_evidence
链接（新）     evidence → LLM 浅提取（Company/Product/Metric，1 次 flash 调用/条）
                       + 词典匹配（subject 兜底 / dimension / stage）
                       + 向量计算（bge-m3，d 集群 GPU）
                       → keyword + link + vector，幂等 upsert
广度扫描（新） subject×dimension×stage 共现 → candidate observation
                       → 对比水位线 → 雷达低置信信号
深度判断       pull(主体×维度) 时间线 → LLM 精读 → observation/finding/水位线
```

三条铁律：
- **批量侧只有浅任务**——单次调用、扁平输出、无重试链、按 prompt_version 缓存；
- **LLM 深判断只在 task-time**——与 9-17 定的"判断是核心"一致；
- **一切结构可重算**——词典/词表/prompt 改了，删掉投影重跑，无沉没成本。

---

## 4. 数据模型

### 4.1 L0 证据层（已有，修复项）

kg_evidence 全部保留。Qdrant 侧 7000 字截断只影响向量库，不影响真源。公告 PDF 已 purge（39,945 份），需完整原文时从数据源重下（运维项，不阻塞）。

### 4.2 L1 链接层（新建，PostgreSQL）

```sql
keyword(keyword_id PK, layer, norm_text, display_text, aliases JSONB,
        status, merged_into, created_at)
  -- layer ∈ {subject, dimension, stage, scope}
  -- status ∈ {active, candidate, merged, retired}
  -- UNIQUE(layer, norm_text)

link(keyword_id, evidence_id, span_start, span_end, source, created_at)
  -- source ∈ {llm, dictionary}
  -- PK(keyword_id, evidence_id, span_start)
```

**双通道分工：**

| 通道 | 覆层 | 机制 | 性质 |
|---|---|---|---|
| LLM 浅提取 | subject（含非上市主体）/ scope（产品/技术名）/ metric（**带数值**） | 类型受约束关键字提取，1 次 flash 调用/条，输出 ~100 token | 精确、开放类、surface form |
| 词典匹配 | subject 兜底 / dimension / stage | AC 自动机 + 别名表 | 确定性、封闭类、水位线地基 |
| 向量 | 语义层 | bge-m3（d 集群 GPU，现有） | 换说法桥接、聚类归并、概念附着 |

**LLM 浅提取任务定义**（v1）：

```text
从下文中提取三类关键字，只输出原文出现过的表述：
- COMPANY: 公司名（上市/非上市/境外均算）
- PRODUCT: 产品、技术、产线、材料名
- METRIC: 指标名，带数值时输出 {"name","value","unit","period"}

规则：保留原文表述不改写（"8英寸抛光硅片"不得缩写为"硅片"）；
不提取行业泛称；不确定的不提取。
输出: {"company": [...], "product": [...], "metric": [...]}
```

约束：只出 surface form 不归一（归一化由别名表机械化完成，**LLM 提议、词典裁决**）；只用 flash 模型（永不引入推理模型）；结果按 prompt_version 缓存。成本估算：27.6 万条 × (~2.5k input + ~100 output token) ≈ 6.9 亿/0.28 亿 token，22 RPM 下约 9 天，增量分钟级；产出率 ~100%（对比旧管线 3%）。

**词表治理闭环**：LLM 提取的未映射 surface form 以 `status=candidate` 直接建 keyword 并建链（recall 优先），经审核/归并后收敛——**embedding 提议涌现簇（周期性无监督聚类发现新主题），词典裁决固化**，形成开放词表的生长机制。

### 4.3 L2 判断层（承接 9-17 台账草案，三点修订）

数据结构（observation / finding / watermark）**继承 9-17 草案 v0.1 全部字段**，修订：

1. **observation 双源产生**：机械候选（subject×dimension×stage 共现，零 LLM，`written_by=pipeline, status=candidate`）+ task-time 确认（`written_by=agent, status=verified`）。机械候选同时是广度触发器：候选对比水位线即产雷达低置信信号，全市场扫描零 LLM。
2. **METRIC 类候选观察带数值**：metric 关键字与数值同句（span 邻近约束）时生成 `{num, unit, period, metric}` 数值候选，横截面对比（scan）与时间序列的数据来源。
3. **finding 支撑锚点细化到句级**：`supports` 每项为 `{obs_id, evidence_id, span_start, span_end}`（SearchAtlas 硬证据闸门），无锚点写入被接口拒绝。

存储：PostgreSQL（唯一约束去重、SQL 聚合水位线、与词法检索同库）。

### 4.4 板块 / 概念 / 主题：三层设计（向量通道职责）

```
第 1 层  官方分类（已有）   Tushare 概念 / SW 行业 → 公司级归属（权威但粗、滞后）
第 2 层  Evidence 级附着    每条 evidence 向量 vs 概念质心 → 这篇公告讲的是哪个主题
第 3 层  涌现聚类           周期性对 evidence 向量无监督聚类 → 发现官方分类没有的新主题
                          → 涌现簇经审核固化为 scope 关键字（喂词表治理闭环）
```

### 4.5 现有存储的去留

| 存储 | 处置 |
|---|---|
| Mongo `kg_evidence` | **保留**，L0 真源 |
| Postgres | **保留并扩展**：keyword/link/observation/finding/watermark + 全文检索（pg_trgm 起步，zhparser 视需要） |
| Neo4j | **冻结只读**：停写；`expand(upstream/downstream)` 过渡期保留，链接层承接传导后退役 |
| Qdrant `doc_chunks` | **保留**（向量通道的载体） |
| Qdrant `kg_entities`/`kg_relations` | **冻结/退役**（三元组的投影） |
| Qdrant `qa_flash` | 保留 |
| PG `signals` 管线 | **退役**，由机械候选 observation 接替；过渡期写适配器保持雷达 UI 不动 |
| 251,951 条 pending combined jobs | **作废**，不再发放 |

---

## 5. 检索设计

### 5.1 三类查询形态与三个原语

| 形态 | 典型问题 | 原语 | 主通道 | 状态依赖 |
|---|---|---|---|---|
| 时间线 | 中晶科技产线进展的演进 | `pull_history(subject, dimension?, scope?, before?)` | 关键字 | 水位线 |
| 横截面 | 同一产品不同公司毛利率 | `scan(dimension, scope?, as_of?)` | 关键字 + observation 数值 | 低 |
| 主题聚合 | AI 算力板块的新变化 | `browse(theme, since?)` | 向量概念层 | 概念映射 |

设计纪律：**top-k 相似性采样是对时间线的有偏采样**（before-state 常漏），判断类任务必须走 `pull_history`；`search_evidence`（向量+词法混合）保留为探索/冷启动入口。preflight `_pre_search()` 按任务类型路由，不再对判断型任务无差别注入。

### 5.2 雷达与法官：同一数据，两种策略

| 消费者 | 需要什么 | 检索策略 |
|---|---|---|
| SignalRadar（广度） | 只看增量 | **水位线过滤**，只出 delta |
| judge（深度） | 完整时间线**含 before-state** | **不过滤**，全量有序拉取 |

### 5.3 Embedding 的岗位（与关键字并列的第一通道）

1. **冷启动发现**（页面/关键字尚不存在的主体）；
2. **换说法桥接**（"8寸抛光片" ≈ "8英寸抛光硅片"，查询时扩展链接邻域）；
3. **开放词表归并**（scope 层 surface form 聚类成规范键）；
4. **概念/主题聚合**（§4.4 三层）；
5. **粗筛路由**（大语料候选生成，保 recall）。

被剥夺：对判断任务做最终排序的权力。主路径的"时间排序 + 水位线 + 去重"即 MMR 式互补性近似的等价实现。

### 5.4 单跳聚合工具族

"公司有哪些产品 / 产品的玩家有哪些 / 客户是谁"同构：`keyword → evidence → 另一层 keyword` 的倒排索引聚合（亚秒级）。质量分层：聚合结果带频次/最近提及/阶段共现置信度，供快速画像；可靠结论回指原文。共现 ≠ 自产，靠 span 邻近（产品与 stage 词同句）+ 频次 + 时间衰减消歧。

---

## 6. Agent 行为设计（借鉴点落地）

1. **先拉历史再判断（HypoSearch）**：divergence-mining skill 改造为"pull 历史探索 → 检测分歧 → 才开证据分支 → 比较分支级证据"。
2. **隔离评判（IBIS）**：挖掘 pass 提候选 finding，干净上下文评判 pass 验证，落实判断可比性。
3. **已消费降权（ITER）**：task 内维护已读 evidence 集合，重排时降权。
4. **句级窄归因（SearchAtlas）**：write_observation / write_finding 强制带 evidence_id + span。

**工具面改造：新增 `pull_history` / `scan` / `browse` / `lookup_products` / `lookup_players` / `lookup_customers` / `backlinks` / `write_observation` / `write_finding` / `watermark`；`_compute_gap` / `neo4j_kg_search` 立即退役；`resolve`/`expand` 过渡期只读保留（承接传导查询），Neo4j 退役时一并退役；`fetch_evidence` / `search_evidence` 保留。**

---

## 7. 迁移路径（双轨并行，证明更优再退役）

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0 评估基线** | gold set：50 条真实查询起步（分层：单点/多跳/对照/歧义 + hard negatives），目标 150–300 | gold set v1 + 评估脚本可用 |
| **P1 链接层** | PG 建表 + 种子词表 + LLM 浅提取 + 词典匹配 + 全量回填 | link 表就绪，抽样人审链接精度 |
| **P2 检索切换** | pull/scan/browse/lookup 原语 + 工具注册 + skill 改造；与现有检索双轨 A/B | gold set 上 Recall@k 与 citation accuracy 不劣于基线 |
| **P3 台账落位** | observation/finding/watermark + 写回 + 机械候选 + 雷达切换 | 雷达信号全量产出，重复率下降 |
| **P4 退役** | 停发 combined jobs；冻结 Neo4j；退役 `kg_entities`/`kg_relations`、signals 管线 | 系统无三元组依赖 |

---

## 8. 评估方案

- **检索层**：Recall@k（k = 实际喂给模型的量）首要；citation accuracy（引用真实且支持 claim）与 faithfulness 权重高于语义相似指标。
- **台账层**：递进检出准确率/漏报率、首次检出提前天数、重复率、追溯完整率、事件后 N 日表现（回测）。
- **过程级**：AgenticRAG-FP 式干预归因：注入认证故障定位丢信号的环节。
- **防坑**：合成查询人工抽审；agentic 评测固定 harness 与呈现方式。

## 9. 非目标

1. 不做全量 LLM 深抽取/编译；2. 不做重预计算图谱；3. 雷达 Phase 1 只做词典命中的廉价触发；4. 知识层边界不变；5. 长文档的 PageIndex 式文档内树暂不做。

## 10. 风险与开放问题

| # | 风险/问题 | 缓解/状态 |
|---|---|---|
| 1 | LLM 浅提取引入后，flash 模型可用性/限速成为回填节奏约束 | 22 RPM ≈ 9 天全量；缓存 + 断点续跑；增量分钟级 |
| 2 | 词表治理是长期成本 | owner + 周期收敛；candidate → active 需审核 |
| 3 | 共现 ≠ 自产（单跳聚合污染） | span 邻近 + 频次 + 时间衰减；结论回指原文 |
| 4 | 机械 stage 匹配精度天花板 | 雷达信号定位低置信"线索"；task-time 深挖兜底 |
| 5 | 判断口径漂移 | IBIS 隔离 + 阶梯 few-shot + 台账留痕 |
| 6 | 传导方向性丢失（关键字共现无向） | task-time 读原文判方向；Neo4j 过渡期只读 |
| 7 | dimension 词表收敛节奏 | 8–10 个种子维度起步，agent 扩展，周期收敛 |

---

## 附录 A：关键决策记录

| # | 决策 | 理由 |
|---|---|---|
| 1 | 摒弃三元组批抽取，改双通道链接层 + 台账 | 成本从"预付"变"按需"；错误从"烙死"变"可重算" |
| 2 | 批量侧允许浅 LLM（类型受约束关键字提取），禁止深抽取 | 三元组死于输出复杂度与归一化负担，非死于"用 LLM" |
| 3 | LLM 只出 surface form，归一化永远机械 | 旧系统死因的直接隔离 |
| 4 | METRIC 提取带数值 | 横截面对比与时间序列需要数值，同调用零边际成本 |
| 5 | dimension/stage 保持词典匹配 | 水位线地基要确定性 |
| 6 | 台账承接 9-17 草案，observation 双源写入 | 机械候选同时实现广度触发器 |
| 7 | embedding 升级为第一通道（语义聚合/概念/主题） | 行业/主题类预期差与跨主体查询需要 |
| 8 | 新结构存 PG；Neo4j 冻结只读而非立即退役 | 唯一约束 + SQL 水位线 + 同库全文检索；降低迁移风险 |
| 9 | 雷达 = 机械候选 × 水位线 delta | 全市场扫描零 LLM |

## 附录 B：参考来源

- 项目内：《预期差的理解与设想》《findings 判断台账设计草案 v0.1》《检索架构与预期差路线调研》（2026-09-17）
- PageIndex（Vectify AI，2025-09）；WikiLLM / Karpathy llm-wiki gist（2026-04）；WiCER（arXiv:2605.07068）
- Argus（2605.16217）；ITER（2608.27912）；HypoSearch（2609.01294）；SearchAtlas（2609.10901）；IBIS/NIS（2608.23045）；AgenticRAG-FP（2608.20627）
