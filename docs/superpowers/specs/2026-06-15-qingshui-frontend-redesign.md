# 清水投研 · 前端重新设计方案

**日期：** 2026-06-15
**方向：** Ledger / 账本风格（B）
**状态：** 已确认

---

## 1. 设计方向

**主题：** 把投研系统做成一本打开的**活页账本**——专业、严肃、有秩序感。

用户每次分析是一笔"账目"，报告是一页"账页"，侧栏是"目录索引"。所有视觉语言围绕"有秩序的专业感"展开。

**签名元素（Signature）：**
- **装订线装饰**（左侧 spine 区域的装订线视觉 + 过渡动效）
- **合规印鉴**（取代文字合规声明，做成印章样式）

---

## 2. 色彩系统

| Token | 色值 | 用途 |
|-------|------|------|
| `--ledger-paper` | `#F5F2EB` | 主背景——古纸色 |
| `--ledger-ink` | `#1A1814` | 主文字——墨黑 |
| `--ledger-rule` | `#D4CFC4` | 格线、分隔线 |
| `--ledger-blue` | `#3B5BDB` | 链接、强调 |
| `--ledger-red` | `#C0392B` | 负数、错误 |
| `--ledger-gold` | `#B8860B` | 印鉴、合规印章 |
| `--ledger-gray` | `#6B7280` | 次要文字 |
| `--ledger-spine` | `#1E1C18` | 侧栏/书脊色 |
| `--ledger-spine-accent` | `#2C2419` | 侧栏 hover |
| `--ledger-entry` | `#FAFAF7` | 卡片/账页底色 |

---

## 3. 字体系统

| 角色 | 字型 | 说明 |
|------|------|------|
| Display | `Noto Serif SC` | 标题、报告 H1/H2 |
| UI | `DM Sans` | 界面文字、标签 |
| Mono | `JetBrains Mono` | 代码、数据 |

---

## 4. 布局结构

```
┌─────────────┬────────────────────────────────────┐
│             │  ← ledger paper 区域（主内容）        │
│  装订线     │  ┌──────────────────────────────┐  │
│  spine      │  │  格线背景 + 账页卡片           │  │
│  (260px)    │  │                              │  │
│             │  └──────────────────────────────┘  │
└─────────────┴────────────────────────────────────┘
```

- **Spine（侧栏）：** 深墨色，宽度 260px，做装订线视觉装饰（左边缘打孔圆点 motif）
- **Main（主区）：** 古纸色背景，内含格线纹理（CSS repeating-linear-gradient）

---

## 5. 组件变更

### 5.1 App.vue 全局样式

- 删除 `--accent-gold` / `--accent-blue` / `--bg-main` 等旧 token，替换为 ledger token
- 删除 `fade-up/slide-right` 动画（保留 `fade-in`），用更克制的 entrance
- 移除暗色背景渐变装饰（radial-gradient）
- 添加格线背景纹理（`--bg-main` 改为带格线的古纸色）
- `.report-body` 样式迁移到 ledger 语义

### 5.2 Sidebar.vue → 重构为 Ledger Spine

**视觉变化：**
- 整体色调改为深墨色（`--ledger-spine`）
- 左边缘添加**装订线打孔** SVG 装饰（垂直排列的圆点 motif，每个圆点 = 一个"账目"入口）
- Logo 区域改为简洁的账本图标
- "开启新咨询"按钮改为"新建账目"语义
- 历史对话区域：每个条目用 ledger rule 分割，条目之间加细线
- "快捷入口"改为"快速分类"并去掉 pill 样式，改用简洁文本链接
- 底部状态改为"系统正常"（ledger 风格字体）

**动画：** 仅保留 fade-in，条目逐个淡入（无 slide 效果）

### 5.3 WelcomeSection.vue → 账本首页

**视觉变化：**
- 移除现有 welcome 布局，改为**账本封面感**
- 顶部用 Noto Serif SC 大字标题："观仓投研"（48px，letter-spacing 拉开）
- 副标题："专业投研报告"（小号衬线体）
- 用 SVG 做一条**羽毛分隔线**（细线 + 羽毛笔意象）替代原有虚线装饰
- 快速入口改为 3 个**账页标签**样式（带孔边的矩形卡片，模拟账页）
- 每个快速入口 hover 时：该账页微微翻起（rotateX + shadow）

**动画：** 页面加载时标题逐字淡入（staggered fade-in，每字延迟 30ms）

### 5.4 Home.vue → 账本页

**视觉变化：**
- 主区域背景改为古纸色 + 格线
- 报告区域改为**账页卡片**：白底（`--ledger-entry`），四周留白大，像一页账纸
- 账页顶部添加格线标题区
- 报告与 chat 分隔改为**双线规则**（两条细线之间加细点序列）
- "合规印鉴"做成印章样式（红色方框 + 假篆字效果，文字居中）
- 错误状态卡片改为红色墨水风格（边框 + 背景）

**动画：** 仅保留 fade-in，不做 slide/fade-up

### 5.5 CustomMarkdownRenderer.vue

**视觉变化：**
- 整体色调整体偏暖（与 ledger paper 协调）
- H1/H2 底部加 ledger rule 格线装饰
- 代码块改为深墨色背景（`--ledger-spine`）+ 金色代码
- Blockquote 改为左侧 ledger rule 线（去掉浅色背景）
- 股票 ID 标签：`--ledger-blue` 边框，浅蓝背景
- 引用标签：`--ledger-gold` 边框，金色背景

### 5.6 ReportView.vue

**视觉变化：**
- 整体风格与 Home.vue 账页一致
- 返回链接改为"← 账目列表"
- 快捷问题改为账页标签样式
- 账页卡片布局与 Home.vue 报告区一致
- 合规印章样式统一

### 5.7 ThinkingPanel.vue / ToolCallStep.vue

- 保持现有功能，不做大改
- 色调整体迁移到 ledger 系统（深墨/金色主调）

---

## 6. 动效规范

**原则：克制、专业、无多余装饰**

| 动效 | 规格 |
|------|------|
| 页面进入 | `fade-in 0.3s ease` |
| 账页悬停 | `translateY(-2px) + shadow 增强`，`0.2s` |
| 快速入口悬停 | 微微翻页感 `rotateX(2deg)`，`0.2s` |
| 装订线打孔 | 页面加载时逐个淡入，每孔延迟 50ms |
| 标题逐字淡入 | `staggered fade-in`，每字 30ms |
| 全局 | 无 bounce、无人为延迟、无多余 keyframe |

---

## 7. 实现优先级

1. **App.vue** — 全局 token 系统重构（基础）
2. **Sidebar.vue** — Ledger Spine 重构（高优先级 UI）
3. **WelcomeSection.vue** — 账本封面感（用户第一印象）
4. **Home.vue** — 账页报告区 + 合规印鉴
5. **CustomMarkdownRenderer.vue** — 色彩迁移
6. **ReportView.vue** — 风格统一
7. **ThinkingPanel / ToolCallStep** — 色彩微调

---

## 8. 测试要点

- [ ] 页面加载性能（无多余动画阻塞）
- [ ] 移动端适配（spine 折叠为 hamburger 菜单）
- [ ] 暗色/亮色模式（ledger 风格仅保留一种模式）
- [ ] 合规印章在不同报告长度下不遮挡内容
- [ ] 快速入口翻页动效在移动端无异常
