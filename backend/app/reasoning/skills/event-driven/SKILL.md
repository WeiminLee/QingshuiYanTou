---
name: event-driven
description: 事件驱动分析，评估公告、新闻、政策事件对股价的影响方向和程度
version: 1.0.0
metadata:
  tags: [事件驱动, 公告, 新闻, 催化剂]
  category: finance
  related_skills: [stock-deep-dive, divergence-mining]
---

# 事件驱动分析

## 触发条件
- 用户询问某个事件对股票的影响
- 用户提到某条新闻/公告要求分析
- 用户问"最近有什么利好/利空"

## 分析流程

### 第一步：事件收集
1. `find_events` → 搜索国内 A 股相关新闻事件
2. `get_event_detail` → 获取感兴趣事件的全文内容

### 第二步：外部视角
3. `tavily_search` → 补充外部媒体和机构观点
4. `web_fetch` → 获取重要链接的全文

### 第三步：官方信息
5. `get_announcement` → 查看相关官方公告
6. `get_irm` → 查看投资者互动记录

### 第四步：影响分析
7. `resolve("涉及公司")` → 锚定图谱实体
8. `expand(entity_id, select=["relations"])` → 查看影响传导链

### 第五步：价格验证
9. `get_kline` → 观察事件前后价格反应

## 关键工具
- find_events, get_event_detail, tavily_search, web_fetch
- get_announcement, get_irm
- resolve, expand
- get_kline

## 输出要求
- 事件分类：利好/利空/中性
- 影响程度评估：重大/中等/轻微
- 影响路径分析：直接影响 vs 间接传导
- 时间维度：短期冲击 vs 长期趋势
- 标注信息来源和可信度

## 陷阱
- 不要过度解读单一事件
- 区分市场预期内和预期外事件
- 注意事件的时间衰减效应
- 公告标题可能误导，必须阅读全文
