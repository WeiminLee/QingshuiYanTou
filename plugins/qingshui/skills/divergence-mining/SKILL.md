---
name: divergence-mining
description: "预期差挖掘——在证据时间线上识别状态演进（递进/变化/矛盾），判断须引用 EV:，判断后沉淀 write_finding"
version: 4.0.0
metadata:
  tags: [预期差, 状态演进, 信息差, 时间差, 判断沉淀]
  category: finance
---

# 预期差挖掘（Evidence-first）

## 定义（硬约束）
预期差 = **状态演进 / 边际变化**本身，不是「实际值 − 一致预期」。
不要引入卖方一致预期基线。判断必须能落到 `evidence_id`（`EV:…`）。

## 触发
用户要求板块/公司预期差、深度基本面挖掘、是否充分定价。

## 流程（先探索后承诺）
1. **横向**：`compare_metric(dimension, scope=板块词)` → 表「主体 | 数值 | 期间」，保留 evidence_id
2. **层次**：`rollup_metric(parent="营收"|相关粗标尺)` → 子指标与命中量
3. **传导**：`propagate_along(start=板块词)` / `related_nodes` → 指标/阶段/公司共现面
4. **纵向**：挑 1–2 个有代表性的主体 `metric_trend(subject, dimension)` → 时间线状态演进
5. **验证**：对关键判断点 `fetch_evidence(EV:…)`；语义搜索仅冷启动

## 沉淀（挖掘之后的维护——判断可复用）
分析完成后把结论沉进判断台账，下次分析先查台账、水位线内不重复断言旧闻：

1. **先查**：`history_findings(subject=主体, dimension=维度)` → 已有观察时间线 + 判断 + 当前水位线（max_level）
2. **对照**：本次新观察 vs 水位线——**只有站上新台阶才是预期差**；与已有判断等价的，只在分析中引用 finding_id，不重复沉淀
3. **观察点**：把本次句级锚定的原始表述/指标点写入 `write_observation`（带 stage_raw/level 或 metric_value）→ 返回 `is_new_level`
4. **判断**：新台阶/恶化/传导/矛盾成立时 `write_finding`：
   - `kind`：progression（递进）| regression（恶化）| new_event（新增事件）| association（关联传导）| divergence（矛盾）
   - `supports`：本分析的 EV 句锚 `[{evidence_id, span_start, span_end}]`（硬闸门：伪造/越界会拒写）
   - `to_state`：`{level, stage}` 落归一化阶梯；`judgment` 一句话结论
   - 幂等：同支撑集重复写入自动合并，重跑分析安全
5. **佐证可溯源**：报告引用判断时附 finding_id（`FD:…`），证据引用照旧附 `EV:…`

## 硅片板块样例输出结构
对「对硅片板块做预期差分析」必须产出类似结构的 Markdown：
- 数据口径说明（主体 ts_code、scope 硅片、period 不可跨口径直比）
- `## 横向预期差：营业收入 × 硅片` 表（主体/数值/期间）
- `## 横向预期差：毛利率 × 硅片` 表
- `## 横向预期差：归属于上市公司股东的净利润 × 硅片` 表（或最接近的利润标尺）
- `## 层次预期差：营收细分`
- `## 传导面（共现）` 指标/阶段/公司
- `## 纵向预期差：<ts_code> 营业收入时间线`
- `## 判断要点`：每条结论附 ≥1 个 `evidence_id`

## 陷阱
- 先下结论再找证据
- 把「实际−共识」当预期差
- period/单位不一致却做排名解读
- 判断不带 EV:
