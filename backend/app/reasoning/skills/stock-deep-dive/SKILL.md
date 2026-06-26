---
name: stock-deep-dive
description: 个股深度分析，从基本面、技术面、产业链、事件四个维度全面评估
version: 1.0.0
metadata:
  tags: [个股, 基本面, 技术面, 估值, 产业链]
  category: finance
  related_skills: [event-driven, supply-chain, divergence-mining]
---

# 个股深度分析

## 触发条件
- 用户明确询问某只股票/公司的分析或评估
- 用户要求评估某公司的投资价值或基本面
- 用户提到具体股票代码或简称并询问"怎么看"

## 分析流程

### 第一步：公司画像
1. `resolve("股票名")` → 锚定图谱实体
2. `expand(entity_id, select=["properties","metrics"])` → 获取公司属性和量化指标
3. `get_stock_profile` → 补充主营业务、行业分类等基本信息

### 第二步：技术面
4. `get_kline` → 获取 K 线数据，观察趋势和估值分位

### 第三步：基本面
5. `get_research_report` → 获取最新研报观点
6. `get_announcement` → 查看近期公告
7. `get_irm` → 查看投资者关系互动记录

### 第四步：事件与舆情
8. `find_events` → 搜索国内相关新闻事件（优先于 tavily_search）
9. `tavily_search` → 补充外部视角和政策动态

### 第五步：可视化
10. `present_chart` → 渲染 K 线/指标图表（最后调用）

## 关键工具
- resolve, expand, get_stock_profile, get_kline
- get_research_report, get_announcement, get_irm
- find_events, get_event_detail, tavily_search
- present_chart

## 输出要求
- 使用结构化报告格式：核心逻辑链 → 关键数据支撑 → 催化剂日历 → 风险矩阵 → 情景推演 → 跟踪指标
- 所有定量结论必须追溯到 L1 证据（fetch_evidence）
- 不确定处标注 TIER 置信度等级
- 报告末尾附"本报告不构成投资建议"

## 陷阱
- 不要仅凭单一指标（如 PE）下结论
- 不要忽略产业链传导效应
- 技术面分析需结合基本面验证
- 研报观点需交叉验证，不可单一来源采信
