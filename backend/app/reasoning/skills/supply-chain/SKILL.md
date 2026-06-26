---
name: supply-chain
description: 产业链传导分析，追踪上下游关系、传导路径和竞争格局
version: 1.0.0
metadata:
  tags: [产业链, 供应链, 上下游, 竞争]
  category: finance
  related_skills: [industry-state, divergence-mining]
---

# 产业链传导分析

## 触发条件
- 用户询问产业链上下游关系
- 用户要求分析某个环节变化对整条链的影响
- 用户询问供应商/客户关系

## 分析流程

### 第一步：产业链结构
1. `resolve("核心公司")` → 锚定实体
2. `expand(entity_id, select=["upstream","downstream"], filter={depth:3})` → 获取上下游

### 第二步：路径分析
3. `neo4j_path` → 补充任意两点间最短路径（resolve/expand 不支持时使用）

### 第三步：竞争格局
4. `expand(entity_id, select=["peers"])` → 获取竞争对手

### 第四步：预期差视角
5. `expand(entity_id, select=["divergence"])` → 查看 Fact vs Estimate 分歧

### 第五步：验证
6. `get_research_report` → 研报验证传导逻辑
7. `tavily_search` → 实时资讯补充催化剂

## 关键工具
- resolve, expand, neo4j_path
- get_research_report, tavily_search

## 输出要求
- 标注各环节的议价能力和利润分配
- 识别关键瓶颈和替代风险
- 分析传导方向和时滞

## 陷阱
- 产业链关系可能随时间和政策变化
- 不要假设线性传导，注意反馈循环
- 区分直接供应商和间接供应商
- 注意进口替代和国产化趋势
