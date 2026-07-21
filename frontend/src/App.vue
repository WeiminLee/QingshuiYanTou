<template>
  <div id="app">
    <router-view />
  </div>
</template>

<script setup></script>

<style>
/* ── Design Tokens — Ink & Ledger ──────────────────────── */
/*
  Product: 清水投研系统 — AI investment research
  Aesthetic: Ink & Ledger — antique gold on warm rice paper
  Reference: Chinese financial documents, ink wash, gold leaf
*/
:root {
  /* ── Ledger Ink — 墨黑色 ──────────────────────────── */
  --ledger-ink: #1a1814;

  /* ── Ledger Paper — 古纸色 ───────────────────────── */
  --ledger-paper: #f5f2eb;
  --ledger-entry: #fafaf7;
  --ledger-rule: #d4cfc4;
  --ledger-blue: #3b5bdb;
  --ledger-red: #c0392b;
  --ledger-gold: #b8860b;
  --ledger-gray: #6b7280;

  /* ── Ledger Spine — 书脊深墨色 ───────────────────── */
  --ledger-spine: #1e1c18;
  --ledger-spine-2: #2a2620;
  --ledger-spine-3: #353028;
  --ledger-spine-accent: #2c2419;

  /* ── Typography ────────────────────────────────── */
  --font-display: "Noto Serif SC", "Source Serif 4", Georgia, serif;
  --font-ui: "DM Sans", "Noto Sans SC", -apple-system, sans-serif;
  --font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;

  /* ── Aliases — 兼容现有组件 ──────────────────────── */
  --bg-main: var(--ledger-paper);
  --bg-main-card: var(--ledger-entry);
  --bg-main-raised: var(--ledger-entry);
  --bg-sidebar: var(--ledger-spine);
  --bg-sidebar-2: var(--ledger-spine-2);
  --bg-sidebar-3: var(--ledger-spine-3);
  --accent-gold: var(--ledger-gold);
  --accent-gold-dim: rgba(184, 134, 11, 0.1);
  --accent-gold-glow: rgba(184, 134, 11, 0.04);
  --accent-blue: var(--ledger-blue);
  --accent-blue-dim: rgba(59, 91, 219, 0.1);
  --accent-blue-deep: var(--ledger-blue);
  --text-main: var(--ledger-ink);
  --text-main-2: #4a4a48;
  --text-main-3: var(--ledger-gray);
  --text-sidebar: #a09888;
  --text-sidebar-muted: #6a6258;
  --text-sidebar-hi: #d8d0c0;
  --border-sidebar: rgba(184, 134, 11, 0.12);
  --border-light: rgba(0, 0, 0, 0.07);
  --border-light-2: rgba(0, 0, 0, 0.12);
  --status-success: #2d9e6c;
  --status-running: var(--ledger-blue);
  --status-error: var(--ledger-red);

  /* ── open-webui 对话区设计令牌（--ow-*）─────────────────
     借鉴 open-webui 极简中性风，仅用于 agent 对话区（.main）。
     不影响侧边栏/其它页的 --ledger-* 主题。 */
  /* 亮色 */
  --ow-bg: #ffffff;            /* 底 */
  --ow-surface: #f9fafb;       /* 面：气泡/工具面板 gray-50 */
  --ow-surface-2: #f3f4f6;     /* 更深面 gray-100 */
  --ow-border: #ececee;        /* 细边 gray-100 */
  --ow-border-strong: #e2e2e5; /* 稍强边 */
  --ow-text: #1f2937;          /* 文字主 gray-800 */
  --ow-text-2: #6b7280;        /* 文字次 gray-500 */
  --ow-text-3: #9ca3af;        /* 文字弱 gray-400 */
  --ow-accent: #0ea5e9;        /* 强调 sky-500 */
  --ow-accent-soft: rgba(14, 165, 233, 0.1);
  --ow-hover: rgba(0, 0, 0, 0.05);   /* hover:bg-black/5 */
  --ow-success: #10b981;
  --ow-error: #ef4444;
  --ow-code-bg: #f6f6f7;

  /* 字体：干净 sans 栈（Mac 上 -apple-system 接近 Inter 观感，无网络依赖） */
  --ow-font: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", "Noto Sans SC", sans-serif;
  --ow-font-mono: "SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, monospace;

  /* 圆角 */
  --ow-radius-lg: 24px;  /* 气泡/输入框 */
  --ow-radius-md: 16px;  /* 卡片 */
  --ow-radius-sm: 12px;  /* chips */
  --ow-radius-xs: 8px;   /* 小元素 */
}

/* ── Global Reset ──────────────────────────────────────── */
*,
*::before,
*::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html {
  font-size: 16px;
}

body {
  font-family: var(--font-ui);
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
      rgba(212, 207, 196, 0.15) 27px,
      rgba(212, 207, 196, 0.15) 28px
    );
  background-size:
    100% 28px,
    28px 100%;
  color: var(--text-main);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow: hidden; /* Home.vue 全屏 layout */
}

/* Custom scrollbar */
::-webkit-scrollbar {
  width: 4px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.12);
  border-radius: 2px;
}

/* Text selection */
::selection {
  background: var(--accent-gold-dim);
  color: var(--text-main);
}

/* Smooth scroll */
html {
  scroll-behavior: smooth;
}

/* ── Entrance Animation — 克制版 ─────────────────── */
@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

/* ── T-Chat Avatar — open-webui 中性风 ─────────── */
.t-chat-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.t-chat-avatar--user {
  background: var(--ow-surface-2);
  color: var(--ow-text-2);
}
.t-chat-avatar--assistant {
  background: var(--ow-text);
  color: #fff;
}

/* ── Report Body — open-webui prose 排版 ────────────── */
.report-body {
  font-family: var(--ow-font);
  color: var(--ow-text);
}
.report-body h1 {
  font-size: 22px;
  font-weight: 600;
  margin: 24px 0 12px;
  color: var(--ow-text);
  letter-spacing: -0.01em;
}
.report-body h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 22px 0 10px;
  color: var(--ow-text);
  letter-spacing: -0.01em;
}
.report-body h3 {
  font-size: 15.5px;
  font-weight: 600;
  margin: 18px 0 8px;
  color: var(--ow-text);
}
.report-body p {
  margin: 0 0 12px;
}
.report-body ul,
.report-body ol {
  padding-left: 22px;
  margin: 10px 0;
}
.report-body li {
  margin: 4px 0;
}
.report-body strong {
  font-weight: 600;
  color: var(--ow-text);
}
.report-body a {
  color: var(--ow-accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.report-body code {
  background: var(--ow-code-bg);
  color: var(--ow-text);
  padding: 1.5px 6px;
  border-radius: 6px;
  font-family: var(--ow-font-mono);
  font-size: 13px;
  border: 1px solid var(--ow-border);
}
.report-body pre {
  background: var(--ow-code-bg);
  color: var(--ow-text);
  padding: 14px 16px;
  border-radius: var(--ow-radius-sm);
  overflow-x: auto;
  margin: 14px 0;
  font-family: var(--ow-font-mono);
  font-size: 13px;
  border: 1px solid var(--ow-border);
}
.report-body pre code {
  background: transparent;
  border: none;
  padding: 0;
}
.report-body blockquote {
  border-left: 3px solid var(--ow-border-strong);
  padding: 2px 14px;
  margin: 14px 0;
  color: var(--ow-text-2);
  font-style: normal;
}
.report-body table {
  border-collapse: collapse;
  margin: 14px 0;
  font-size: 14px;
  width: 100%;
}
.report-body th,
.report-body td {
  border: 1px solid var(--ow-border);
  padding: 7px 12px;
  text-align: left;
}
.report-body th {
  background: var(--ow-surface);
  font-weight: 600;
}
.report-body hr {
  border: none;
  border-top: 1px solid var(--ow-border);
  margin: 20px 0;
}
</style>
