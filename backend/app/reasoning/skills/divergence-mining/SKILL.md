---
name: divergence-mining
description: 预期差挖掘，发现 Fact vs Estimate 分歧点，寻找市场尚未充分定价的机会
version: 1.0.0
metadata:
  tags: [预期差, 信息差, 认知差, 时间差]
  category: finance
  related_skills: [stock-deep-dive, event-driven, supply-chain]
---

# 预期差挖掘

## 触发条件
- 用户要求寻找预期差或投资机会
- 用户询问市场是否充分定价了某个因素
- 用户要求做深度基本面挖掘

## 分析流程

### 第一步：分歧发现
1. `resolve("目标公司")` → 锚定实体
2. `expand(entity_id, select=["divergence"])` → Fact vs Estimate 分歧点

### 第二步：向上追溯
3. `expand(entity_id, select=["upstream"])` → 追踪预期差传导来源

### 第三步：横向对比
4. `expand(entity_id, select=["peers"])` → 同行对比验证认知差

### 第四步：证据追溯
5. `fetch_evidence` → L1 证据追溯，确认 Fact 可信度

### 第五步：外部验证
6. `get_research_report` → 券商一致预期参考
7. `tavily_search` → 催化剂和最新动态

## 关键工具
- resolve, expand, fetch_evidence
- get_research_report, tavily_search

## 输出要求
- 列出发现的预期差点（按置信度排序）
- 每条预期差包含：分歧点描述、Fact vs Estimate 对比、证据来源
- 判断预期差类型：信息差/认知差/时间差
- 评估市场修正的可能性和时间窗口

## 陷阱
- Fact 和 Estimate 的区别需要仔细甄别
- 不要将短期波动误判为预期差
- 预期差可能已经被市场消化，需验证时间窗口
- 单一证据不足以支撑结论，需交叉验证
