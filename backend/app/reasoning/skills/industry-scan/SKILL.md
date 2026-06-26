---
name: industry-scan
description: 行业/板块扫描，识别板块热度、轮动机会和市场情绪
version: 1.0.0
metadata:
  tags: [行业, 板块, 轮动, 市场情绪]
  category: finance
  related_skills: [industry-state, supply-chain]
---

# 行业/板块扫描

## 触发条件
- 用户询问某个行业/板块的走势或机会
- 用户要求扫描市场热点或轮动方向
- 用户无具体标的，要求推荐方向

## 分析流程

### 第一步：市场情绪
1. `get_concept_hot` → 获取当前热门概念板块
2. `get_market_breadth` → 获取市场宽度数据，判断整体情绪

### 第二步：行业动态
3. `find_events` → 搜索行业相关新闻和政策动态
4. `tavily_search` → 补充外部行业资讯

### 第三步：产业链视角
5. `resolve("行业关键词")` → 锚定行业核心实体
6. `expand(entity_id, select=["upstream","downstream"])` → 产业链结构

### 第四步：研报验证
7. `get_research_report` → 获取行业研报，验证判断

## 关键工具
- get_concept_hot, get_market_breadth
- find_events, tavily_search
- resolve, expand
- get_research_report

## 输出要求
- 列出当前热门板块及热度排序
- 分析轮动逻辑和持续性
- 标注板块内代表性标的
- 给出关注方向和建议

## 陷阱
- 板块热度可能短期脉冲，需区分趋势和噪音
- 概念板块分类可能不精确，需交叉验证
- 行业研报可能有利益冲突，注意来源可信度
