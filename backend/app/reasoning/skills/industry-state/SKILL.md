---
name: industry-state
description: 行业状态评估，分析竞争格局、景气度、生命周期和政策环境
version: 1.0.0
metadata:
  tags: [行业, 竞争格局, 景气度, 政策]
  category: finance
  related_skills: [industry-scan, supply-chain]
---

# 行业状态评估

## 触发条件
- 用户询问某个行业的竞争格局
- 用户要求评估行业景气度
- 用户询问行业发展趋势

## 分析流程

### 第一步：行业画像
1. `neo4j_industry_state` → 获取行业公司状态分布

### 第二步：竞争分析
2. `resolve("行业代表公司")` → 锚定实体
3. `expand(entity_id, select=["properties","peers"])` → 各公司属性和竞争格局

### 第三步：市场情绪
4. `get_concept_hot` → 板块热度
5. `get_market_breadth` → 市场宽度

## 关键工具
- neo4j_industry_state
- resolve, expand
- get_concept_hot, get_market_breadth

## 输出要求
- 行业生命周期阶段判断
- 竞争格局分析（集中度、龙头地位）
- 景气度指标和趋势
- 政策环境评估

## 陷阱
- 行业分类标准可能不统一
- 景气度指标有滞后性
- 不同细分行业可能处于不同周期阶段
