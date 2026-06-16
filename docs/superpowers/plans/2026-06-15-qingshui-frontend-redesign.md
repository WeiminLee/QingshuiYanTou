# 清水投研 · 前端 Ledger 风格重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将清水投研前端重构为"活页账本"风格 — 专业、严肃、有秩序感

**Architecture:** 
- 全局 CSS Token 系统迁移到 Ledger 语义（古纸色、墨黑、金色）
- 侧栏重构为 Ledger Spine（装订线打孔装饰）
- 主内容区添加格线背景纹理
- 报告区改为账页卡片 + 合规印章样式
- 动效统一为克制的 fade-in

**Tech Stack:** Vue 3 + Element Plus + TDesign Chat + CSS Variables + CSS Grid/Flexbox

---

## File Structure

```
frontend/src/
├── App.vue                           # 全局 Token 系统 + 格线背景
├── views/
│   ├── Home.vue                      # 侧栏 Ledger Spine + 账页卡片
│   └── ReportView.vue               # 风格统一
└── components/
    ├── Sidebar.vue                   # Dashboard 侧栏（非 Home 侧栏）
    ├── WelcomeSection.vue            # 账本封面感
    ├── CustomMarkdownRenderer.vue     # 色彩迁移
    ├── ThinkingPanel.vue             # 色彩微调
    └── ToolCallStep.vue              # 色彩微调
```

---

## Task 1: App.vue — 全局 Token 系统重构

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: 替换设计 Token 为 Ledger 语义**

将现有的 "Ink & Ledger" token 替换为规格中的 Ledger token：

```css
:root {
  /* ── Ledger Paper — 古纸色 ───────────────────────── */
  --ledger-paper:        #F5F2EB;
  --ledger-entry:        #FAFAF7;
  --ledger-rule:         #D4CFC4;
  --ledger-blue:         #3B5BDB;
  --ledger-red:          #C0392B;
  --ledger-gold:         #B8860B;
  --ledger-gray:         #6B7280;

  /* ── Ledger Spine — 书脊深墨色 ───────────────────── */
  --ledger-spine:        #1E1C18;
  --ledger-spine-2:      #2A2620;
  --ledger-spine-3:      #353028;
  --ledger-spine-accent: #2C2419;

  /* ── Typography ──────────────────────────────────── */
  --font-display: 'Noto Serif SC', 'Source Serif 4', Georgia, serif;
  --font-ui:      'DM Sans', 'Noto Sans SC', -apple-system, sans-serif;
  --font-mono:    'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;

  /* ── Aliases — 兼容现有组件 ──────────────────────── */
  --bg-main:           var(--ledger-paper);
  --bg-main-card:      var(--ledger-entry);
  --bg-sidebar:        var(--ledger-spine);
  --bg-sidebar-2:      var(--ledger-spine-2);
  --bg-sidebar-3:      var(--ledger-spine-3);
  --accent-gold:       var(--ledger-gold);
  --accent-gold-dim:   rgba(184,134,11,0.10);
  --accent-gold-glow:  rgba(184,134,11,0.04);
  --accent-blue:       var(--ledger-blue);
  --accent-blue-dim:   rgba(59,91,219,0.10);
  --text-main:         #1A1814;
  --text-main-2:       #4A4A48;
  --text-main-3:       var(--ledger-gray);
  --text-sidebar:      #A09888;
  --text-sidebar-muted:#6A6258;
  --text-sidebar-hi:   #D8D0C0;
  --border-sidebar:    rgba(184,134,11,0.12);
  --border-light:      rgba(0,0,0,0.07);
  --border-light-2:    rgba(0,0,0,0.12);
  --status-success:    #2D9E6C;
  --status-running:    var(--ledger-blue);
  --status-error:      var(--ledger-red);
}
```

- [ ] **Step 2: 添加格线背景纹理**

在 `body` 样式后添加格线背景：

```css
/* ── Ledger Grid Background ────────────────────────── */
body {
  background-color: var(--ledger-paper);
  background-image:
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 27px,
      var(--ledger-rule) 27px,
      var(--ledger-rule) 28px
    ),
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 27px,
      rgba(212,207,196,0.15) 27px,
      rgba(212,207,196,0.15) 28px
    );
  background-size: 100% 28px, 28px 100%;
  background-position: 0 0, 0 0;
}
```

- [ ] **Step 3: 清理冗余动画**

删除 `fade-up`、`slide-right`、`gold-pulse`、`dot-bounce` keyframes，保留 `fade-in`：

```css
/* Entrance animations — 克制版 */
@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
```

- [ ] **Step 4: 更新 .report-body 样式**

```css
.report-body h1 {
  font-family: var(--font-display);
  font-size: 20px; font-weight: 700;
  margin: 24px 0 12px;
  color: var(--ledger-ink, #1A1814);
  border-bottom: 2px solid var(--ledger-rule);
  padding-bottom: 8px;
}
.report-body h2 {
  font-family: var(--font-display);
  font-size: 17px; font-weight: 700;
  margin: 20px 0 10px;
  color: var(--ledger-ink, #1A1814);
  border-bottom: 1px solid var(--ledger-rule);
  padding-bottom: 6px;
}
.report-body code {
  background: var(--ledger-entry);
  color: var(--ledger-gold);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  border: 1px solid var(--ledger-rule);
}
.report-body pre {
  background: var(--ledger-spine);
  color: #D8C89A;
  padding: 14px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 12px 0;
  font-family: var(--font-mono);
  font-size: 12px;
  border: 1px solid var(--border-sidebar);
}
.report-body blockquote {
  border-left: 3px solid var(--ledger-gold);
  padding: 8px 14px;
  background: var(--ledger-entry);
  border-radius: 0 6px 6px 0;
  margin: 14px 0;
  color: var(--text-main-2);
  font-style: normal;
}
```

- [ ] **Step 5: 提交**

```bash
git add frontend/src/App.vue
git commit -m "feat(frontend): migrate to Ledger token system, add grid background

- Replace design tokens with Ledger semantic tokens (paper, spine, gold, blue)
- Add ledger rule grid background texture
- Keep only fade-in animation, remove fade-up/slide-right
- Update .report-body styles with ledger styling

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Home.vue — 侧栏 Ledger Spine + 账页卡片

**Files:**
- Modify: `frontend/src/views/Home.vue`

- [ ] **Step 1: 添加装订线打孔 SVG 装饰**

在 `.sidebar` 样式后添加打孔装饰：

```css
/* ── Ledger Spine Binding Holes ────────────────────── */
.sidebar {
  position: relative;
}

/* 打孔圆点装饰 — 左侧边缘 */
.sidebar::before {
  content: '';
  position: absolute;
  left: 12px;
  top: 80px;
  bottom: 80px;
  width: 8px;
  background-image: radial-gradient(
    circle at 50% 50%,
    var(--ledger-spine) 5px,
    transparent 6px
  );
  background-size: 8px 40px;
  background-repeat: repeat-y;
  background-position: 0 0;
  opacity: 0.6;
  animation: fade-in 0.6s ease both;
}
```

- [ ] **Step 2: 更新 Logo 区域为账本图标**

将现有的圆形 logo SVG 替换为简洁账本图标：

```html
<div class="sidebar-logo">
  <div class="logo-mark">
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
      <!-- 账本图标 — 翻开的书页 -->
      <rect x="3" y="4" width="9" height="18" rx="1" stroke="#B8860B" stroke-width="1.2" fill="none"/>
      <rect x="14" y="4" width="9" height="18" rx="1" stroke="#B8860B" stroke-width="1.2" fill="none"/>
      <line x1="12" y1="4" x2="12" y2="22" stroke="#B8860B" stroke-width="1.2"/>
      <!-- 中缝虚线 -->
      <line x1="12" y1="7" x2="12" y2="10" stroke="#B8860B" stroke-width="0.8" stroke-dasharray="2 2"/>
      <line x1="12" y1="12" x2="12" y2="15" stroke="#B8860B" stroke-width="0.8" stroke-dasharray="2 2"/>
      <line x1="12" y1="17" x2="12" y2="19" stroke="#B8860B" stroke-width="0.8" stroke-dasharray="2 2"/>
    </svg>
  </div>
  <div class="logo-text">
    <span class="logo-name">清水投研</span>
    <span class="logo-sub">观仓 AI</span>
  </div>
</div>
```

- [ ] **Step 3: 更新"新建账目"按钮语义**

将 `开启新咨询` 按钮文本改为 `新建账目`：

```html
<button class="btn-new-chat" @click="startNewConversation">
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  </svg>
  新建账目
</button>
```

- [ ] **Step 4: 更新历史条目分割线样式**

```css
.sidebar-item {
  /* 保持原有样式，仅调整分割线 */
  border-bottom: 1px solid rgba(184,134,11,0.06);
}
.sidebar-item:last-child {
  border-bottom: none;
}
```

- [ ] **Step 5: 更新"快捷入口"为"快速分类"（去掉 pill 样式）**

```html
<div class="sidebar-section sidebar-categories">
  <div class="sidebar-section-label">快速分类</div>
  <div class="category-list">
    <button
      v-for="cat in categories"
      :key="cat.key"
      class="category-link"
      @click="handleCategoryClick(cat.placeholder)"
    >
      <span class="cat-dot" :style="{ background: cat.color }"/>
      {{ cat.name }}
    </button>
  </div>
</div>
```

```css
.category-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-sidebar);
  transition: color 0.15s;
  text-align: left;
  border-radius: 4px;
}
.category-link:hover {
  background: var(--ledger-spine-3);
  color: var(--text-sidebar-hi);
}
```

- [ ] **Step 6: 更新账页卡片报告区样式**

将 `.report-section` 改为账页卡片样式：

```css
.report-section {
  background: var(--ledger-entry);
  border: 1px solid var(--ledger-rule);
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  padding: 32px 40px;
  margin-top: 24px;
}
```

- [ ] **Step 7: 添加合规印章样式**

将 `.compliance-stamp` 改为印章样式：

```css
.compliance-stamp {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 32px;
  padding: 16px 20px;
  background: var(--ledger-entry);
  border: 2px solid var(--ledger-gold);
  border-radius: 4px;
  font-size: 11px;
  color: var(--ledger-gold);
  line-height: 1.6;
  text-align: center;
  animation: fade-in 0.4s ease both;
  /* 印章效果 */
  position: relative;
  font-weight: 500;
  letter-spacing: 0.5px;
}
.compliance-stamp::before {
  content: '';
  position: absolute;
  inset: 4px;
  border: 1px solid rgba(184,134,11,0.3);
  border-radius: 2px;
  pointer-events: none;
}
.compliance-stamp svg {
  flex-shrink: 0;
  color: var(--ledger-gold);
}
```

- [ ] **Step 8: 更新错误卡片样式**

```css
.error-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: var(--ledger-entry);
  border: 1px solid var(--ledger-red);
  border-radius: 4px;
  color: var(--ledger-red);
  font-size: 13px;
  animation: fade-in 0.3s ease both;
}
```

- [ ] **Step 9: 提交**

```bash
git add frontend/src/views/Home.vue
git commit -m "feat(Home.vue): implement Ledger Spine sidebar with binding holes

- Add binding hole decoration on left edge
- Update logo to ledger/book icon
- Change '开启新咨询' to '新建账目'
- Update history items with ledger rule dividers
- Replace category pills with text links (快速分类)
- Add ledger paper card styling for report section
- Implement compliance stamp with gold border style
- Update error card to ledger red styling

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: WelcomeSection.vue — 账本封面感

**Files:**
- Modify: `frontend/src/components/WelcomeSection.vue`

- [ ] **Step 1: 更新产品名称为大标题**

将 `.welcome-product-name` 改为封面标题：

```css
.welcome-product-name {
  font-family: var(--font-display);
  font-size: 48px;
  font-weight: 700;
  color: var(--ledger-ink, #1A1814);
  margin-bottom: 8px;
  letter-spacing: 8px;
  animation: char-fade-in 0.5s ease both;
}
```

- [ ] **Step 2: 添加羽毛分隔线 SVG**

替换现有的虚线分隔线：

```html
<div class="welcome-ornament">
  <svg width="200" height="20" viewBox="0 0 200 20" fill="none">
    <!-- 羽毛笔分隔线 -->
    <line x1="0" y1="10" x2="80" y2="10" stroke="#D4CFC4" stroke-width="1"/>
    <!-- 羽毛 -->
    <path d="M85 10 Q90 5 95 8 Q92 10 95 12 Q90 15 85 10Z" fill="#B8860B" opacity="0.6"/>
    <path d="M95 10 L100 10" stroke="#B8860B" stroke-width="1"/>
    <line x1="105" y1="10" x2="200" y2="10" stroke="#D4CFC4" stroke-width="1"/>
  </svg>
</div>
```

- [ ] **Step 3: 添加账页标签样式快速入口**

更新 `.quick-chip` 为账页标签样式：

```css
.quick-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px;
  border-radius: 0;
  border: 1px solid var(--ledger-rule);
  background: var(--ledger-entry);
  color: var(--text-main-2);
  font-family: var(--font-ui);
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  box-shadow: 0 2px 6px rgba(0,0,0,0.04);
  transition: all 0.2s;
  animation: fade-in 0.4s ease both;
  /* 账页标签 — 左侧打孔边 */
  position: relative;
}
.quick-chip::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  background-image: radial-gradient(
    circle at 50% 50%,
    var(--ledger-paper) 3px,
    transparent 4px
  );
  background-size: 6px 20px;
  background-repeat: repeat-y;
  background-position: center;
  border-right: 1px solid var(--ledger-rule);
}
.quick-chip:nth-child(1) { animation-delay: 0.1s; }
.quick-chip:nth-child(2) { animation-delay: 0.2s; }
.quick-chip:nth-child(3) { animation-delay: 0.3s; }
.quick-chip:hover {
  border-color: var(--ledger-gold);
  color: var(--text-main);
  transform: rotateX(2deg) translateY(-2px);
  box-shadow: 0 4px 12px rgba(184,134,11,0.12);
}
.quick-chip svg { color: var(--ledger-gold); flex-shrink: 0; }
```

- [ ] **Step 4: 添加逐字淡入动画**

```css
@keyframes char-fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
```

- [ ] **Step 5: 移除 fade-up 动画依赖**

将 `.welcome-inner` 的动画改为 fade-in：

```css
.welcome-inner {
  max-width: 620px;
  width: 100%;
  text-align: center;
  animation: fade-in 0.5s ease both;
  transform: none;
}
```

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/WelcomeSection.vue
git commit -m "feat(WelcomeSection.vue): implement ledger cover page aesthetic

- Update product name to large 48px display title with letter-spacing
- Add feather pen divider SVG ornament
- Implement ledger paper tab style for quick entry buttons with binding holes
- Add page-flip hover effect (rotateX + shadow)
- Keep only fade-in animations

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: CustomMarkdownRenderer.vue — 色彩迁移

**Files:**
- Modify: `frontend/src/components/CustomMarkdownRenderer.vue`

- [ ] **Step 1: 更新基础样式**

```css
.markdown-body :deep(code) {
  background: var(--ledger-entry);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  color: var(--ledger-gold);
  border: 1px solid var(--ledger-rule);
}

.markdown-body :deep(pre) {
  background: var(--ledger-spine);
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  border: 1px solid rgba(184,134,11,0.2);
}

.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
  color: #D8C89A;
}
```

- [ ] **Step 2: 更新 H1/H2 底部格线装饰**

```css
.markdown-body :deep(h1) {
  border-bottom: 2px solid var(--ledger-rule);
  padding-bottom: 8px;
}
.markdown-body :deep(h2) {
  border-bottom: 1px solid var(--ledger-rule);
  padding-bottom: 6px;
}
```

- [ ] **Step 3: 更新 Blockquote 为 Ledger Rule 线**

```css
.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--ledger-gold);
  padding: 8px 14px;
  background: var(--ledger-entry);
  border-radius: 0 4px 4px 0;
  margin: 14px 0;
  color: var(--text-main-2);
}
```

- [ ] **Step 4: 更新链接颜色**

```css
.markdown-body :deep(a) {
  color: var(--ledger-blue);
  text-decoration: none;
}
.markdown-body :deep(a:hover) {
  text-decoration: underline;
}
```

- [ ] **Step 5: 更新股票 ID 标签样式**

```css
.stock-tag {
  color: var(--ledger-blue);
  cursor: pointer;
  font-size: 12px;
  background: rgba(59,91,219,0.08);
  padding: 2px 6px;
  border-radius: 4px;
  margin: 0 2px;
  border: 1px solid var(--ledger-blue);
  transition: background 0.2s;
}
.stock-tag:hover {
  background: rgba(59,91,219,0.15);
}
```

- [ ] **Step 6: 更新引用标签样式**

```css
.reference-tag {
  color: var(--ledger-blue);
  cursor: pointer;
  font-size: 12px;
  background: rgba(59,91,219,0.08);
  padding: 2px 6px;
  border-radius: 4px;
  margin: 0 2px;
  border: 1px solid rgba(59,91,219,0.3);
  transition: background 0.2s;
}
.reference-tag:hover {
  background: rgba(59,91,219,0.15);
}
```

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/CustomMarkdownRenderer.vue
git commit -m "feat(CustomMarkdownRenderer.vue): migrate to ledger color system

- Update code blocks with ledger-spine background
- Add ledger rule borders to H1/H2
- Update blockquote to left gold rule style
- Migrate links to ledger-blue
- Update stock-tag and reference-tag to ledger-blue styling

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: ReportView.vue — 风格统一

**Files:**
- Modify: `frontend/src/views/ReportView.vue`

- [ ] **Step 1: 更新背景为古纸色**

```css
.report-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px;
  min-height: calc(100vh - 56px);
  display: flex;
  flex-direction: column;
  background: var(--ledger-paper);
}
```

- [ ] **Step 2: 更新返回链接**

```html
<router-link to="/" class="back-link">
  <el-icon><ArrowLeft /></el-icon>
  账目列表
</router-link>
```

```css
.back-link {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-main-2);
  text-decoration: none;
  font-size: 14px;
  transition: color 0.2s;
}
.back-link:hover { color: var(--ledger-gold); }
```

- [ ] **Step 3: 更新问题输入区为账页卡片**

```css
.question-section {
  background: var(--ledger-entry);
  border: 1px solid var(--ledger-rule);
  border-radius: 4px;
  padding: 32px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
.question-title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--ledger-ink, #1A1814);
  margin-bottom: 16px;
  border-bottom: 1px solid var(--ledger-rule);
  padding-bottom: 12px;
}
```

- [ ] **Step 4: 更新快捷问题为账页标签样式**

```css
.quick-tag {
  cursor: pointer;
  background: var(--ledger-entry);
  border: 1px solid var(--ledger-rule);
  color: var(--text-main-2);
  transition: all 0.2s;
}
.quick-tag:hover {
  border-color: var(--ledger-gold);
  color: var(--text-main);
  transform: translateY(-1px);
}
```

- [ ] **Step 5: 更新合规印章样式**

```css
.compliance-stamp {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 32px;
  padding: 16px 20px;
  background: var(--ledger-entry);
  border: 2px solid var(--ledger-gold);
  border-radius: 4px;
  font-size: 11px;
  color: var(--ledger-gold);
  line-height: 1.6;
  text-align: center;
  position: relative;
  font-weight: 500;
  letter-spacing: 0.5px;
}
.compliance-stamp::before {
  content: '';
  position: absolute;
  inset: 4px;
  border: 1px solid rgba(184,134,11,0.3);
  border-radius: 2px;
  pointer-events: none;
}
```

- [ ] **Step 6: 更新错误卡片样式**

```css
.error-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: var(--ledger-entry);
  border: 1px solid var(--ledger-red);
  border-radius: 4px;
  color: var(--ledger-red);
  font-size: 13px;
}
```

- [ ] **Step 7: 提交**

```bash
git add frontend/src/views/ReportView.vue
git commit -m "feat(ReportView.vue): unify ledger style across report page

- Add ledger paper background
- Change '返回首页' to '账目列表'
- Update question section to ledger paper card style
- Implement compliance stamp with gold border
- Update quick tags to ledger tab style
- Migrate error card to ledger red styling

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: ThinkingPanel + ToolCallStep — 色彩微调

**Files:**
- Modify: `frontend/src/components/ThinkingPanel.vue`
- Modify: `frontend/src/components/ToolCallStep.vue`

- [ ] **Step 1: 检查并更新 ThinkingPanel 样式**

读取当前文件后，根据 ledger 风格调整：

```css
/* 如果存在深色背景，替换为 ledger-spine */
.thinking-panel {
  background: var(--ledger-entry);
  border: 1px solid var(--ledger-rule);
  border-radius: 4px;
}
```

- [ ] **Step 2: 检查并更新 ToolCallStep 样式**

```css
/* 如果存在深色背景，替换为 ledger-spine */
.tool-call-step {
  background: var(--ledger-spine);
  border: 1px solid rgba(184,134,11,0.2);
  border-radius: 4px;
  color: #D8C89A;
}
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/ThinkingPanel.vue frontend/src/components/ToolCallStep.vue
git commit -m "feat(panels): migrate ThinkingPanel and ToolCallStep to ledger colors

- Update panel backgrounds to ledger-entry
- Update tool call step to ledger-spine with gold accents

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Sidebar.vue (Dashboard) — 色彩微调

**Files:**
- Modify: `frontend/src/components/Sidebar.vue`

- [ ] **Step 1: 更新 Dashboard 侧栏样式**

将深蓝色背景改为 ledger-spine：

```css
.dashboard-sidebar {
  height: 100%;
  border-right: none;
  background: var(--ledger-spine) !important;
}

.dashboard-sidebar:not(.el-menu--collapse) {
  width: 220px;
}

.dashboard-sidebar .el-menu-item {
  border-left: 3px solid transparent;
  color: var(--text-sidebar);
}

.dashboard-sidebar .el-menu-item.is-active {
  background-color: var(--ledger-spine-accent) !important;
  border-left-color: var(--ledger-gold);
  color: var(--text-sidebar-hi);
}

.dashboard-sidebar .el-menu-item:hover {
  background-color: var(--ledger-spine-3) !important;
  color: var(--text-sidebar-hi);
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/Sidebar.vue
git commit -m "feat(Sidebar.vue): migrate Dashboard sidebar to ledger spine

- Replace deep blue with ledger-spine colors
- Update active state to gold accent
- Sync text colors with ledger palette

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist

### 1. Spec Coverage
- [x] App.vue — 全局 token 系统重构 ✅ Task 1
- [x] Sidebar (Home.vue) — Ledger Spine 重构 + 装订线装饰 ✅ Task 2
- [x] WelcomeSection.vue — 账本封面感 ✅ Task 3
- [x] Home.vue — 账页报告区 + 合规印章 ✅ Task 2
- [x] CustomMarkdownRenderer.vue — 色彩迁移 ✅ Task 4
- [x] ReportView.vue — 风格统一 ✅ Task 5
- [x] ThinkingPanel / ToolCallStep — 色彩微调 ✅ Task 6
- [x] Sidebar.vue (Dashboard) — 色彩微调 ✅ Task 7

### 2. Placeholder Scan
- [x] 无 TBD/TODO 残留
- [x] 无"添加适当错误处理"等模糊描述
- [x] 所有代码步骤包含完整代码块
- [x] 无"类似 Task N"引用

### 3. Type Consistency
- [x] Token 名称一致：ledger-paper, ledger-spine, ledger-gold, ledger-blue, ledger-red
- [x] Font 变量一致：font-display, font-ui, font-mono
- [x] 组件类名一致使用 ledger 前缀

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-15-qingshui-frontend-redesign.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
