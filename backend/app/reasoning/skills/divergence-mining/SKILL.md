---
name: divergence-mining
description: 预期差挖掘，发现 Fact vs Estimate 分歧点，寻找市场尚未充分定价的机会
version: 2.0.0
metadata:
  tags: [预期差, 信息差, 认知差, 时间差]
  category: finance
  related_skills: [stock-deep-dive, event-driven, supply-chain]
---

# 预期差挖掘

## 触发条件
- 用户要求寻找预期差或投资机会
- 用户询问市场是否充分定价了某因素
- 用户要求做深度基本面挖掘

## 核心原则：先探索后承诺（HypoSearch）
不要先入为主选边站，再用检索凑证据；先拉完整历史时间线，在时间线上检测到分歧点，才允许开证据分支。78% 的的预期差挖掘失败源于探索不足，而非推理不足。

## 分析流程

### 第一步：pull_history 历史探索
1. `pull_history(subject, dimension=...)` → 按 (主体×维度) 拉取完整证据时间线
   - 判断递进/变化/矛盾，这是第一入口——不是语义搜索
   - 时间线完整、有序、去重；可用 `before` 向更早翻页
2. 若不确定主体有哪些维度：`lookup_products(company)` 先摸清产品/技术面

### 第二步：分歧检测
3. 在时间线上找分歧点：证据是否递进（认证→量产→放量）？是否变化（口径切换）？是否矛盾（新旧数据打架）？
4. 判断 Fact（已发生）与 Estimate（市场预期）的错位：市场还停在旧水位吗？

### 第三步：才开证据分支（HypoSearch 先探索后承诺）
5. 检测到分歧点后，才按假设开证据分支，每条分支只服务于一个待验证假设
6. 传导验证：`lookup_players(keyword_norm_text)` 查该产品/关键字的玩家 → 传导挖掘入口

### 第四步：分支级证据比较
7. `scan_dimension(dimension, scope=...)` → 横截面：该维度下各主体的证据聚合，跨公司对比验证
8. `backlinks(evidence_id)` → 双向引用：查关键证据的全部关键字及同关键字关联证据，看证据网络是否支持分支假设

### 第五步：fetch_evidence 验证
9. `fetch_evidence(evidence_id)` → 逐条追溯分支内关键证据的原文，确认 Fact 可信度

### 第六步：write_finding 沉淀
10. `write_finding`（T14 后可用）→ 通过验证的分歧点沉淀为 finding，强制带 evidence_id + span

## 关键工具
- pull_history, scan_dimension, lookup_products, lookup_players, backlinks
- fetch_evidence, write_finding（T14 后可用）

## 输出要求
- 列出发现的预期差点（按置信度排序）
- 每条预期差包含：分歧点描述、Fact vs Estimate 对比、证据来源（evidence_id）
- 判断预期差类型：信息差/认知差/时间差
- 评估市场修正的可能性和时间窗口

## 陷阱
- 先承诺后找证据是最大陷阱：没有拉过时间线之前，不要下任何结论
- 语义搜索只做冷启动发现，判断递进/变化/矛盾必须走 pull_history
- Fact 和 Estimate 的区别需要仔细甄别
- 不要将短期波动误判为预期差
- 预期差可能已经被市场消化，需验证时间窗口
- 单一证据不足以支撑结论，需交叉验证
