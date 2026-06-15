<template>
  <div id="app">
    <router-view />
  </div>
</template>

<script setup>
</script>

<style>
/* ── Design Tokens — Ink & Ledger ──────────────────────── */
/*
  Product: 清水投研系统 — AI investment research
  Aesthetic: Ink & Ledger — antique gold on warm rice paper
  Reference: Chinese financial documents, ink wash, gold leaf
*/
:root {
  /* ── Ledger Ink — 墨黑色 ──────────────────────────── */
  --ledger-ink:          #1A1814;

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

  /* ── Typography ────────────────────────────────── */
  --font-display: 'Noto Serif SC', 'Source Serif 4', Georgia, serif;
  --font-ui:      'DM Sans', 'Noto Sans SC', -apple-system, sans-serif;
  --font-mono:    'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;

  /* ── Aliases — 兼容现有组件 ──────────────────────── */
  --bg-main:           var(--ledger-paper);
  --bg-main-card:      var(--ledger-entry);
  --bg-main-raised:    var(--ledger-entry);
  --bg-sidebar:        var(--ledger-spine);
  --bg-sidebar-2:      var(--ledger-spine-2);
  --bg-sidebar-3:      var(--ledger-spine-3);
  --accent-gold:       var(--ledger-gold);
  --accent-gold-dim:   rgba(184,134,11,0.10);
  --accent-gold-glow:  rgba(184,134,11,0.04);
  --accent-blue:       var(--ledger-blue);
  --accent-blue-dim:   rgba(59,91,219,0.10);
  --accent-blue-deep:  var(--ledger-blue);
  --text-main:         var(--ledger-ink);
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

/* ── Global Reset ──────────────────────────────────────── */
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

html { font-size: 16px; }

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
      rgba(212,207,196,0.15) 27px,
      rgba(212,207,196,0.15) 28px
    );
  background-size: 100% 28px, 28px 100%;
  color: var(--text-main);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow: hidden; /* Home.vue 全屏 layout */
}

/* Custom scrollbar */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: rgba(0,0,0,0.12);
  border-radius: 2px;
}

/* Text selection */
::selection { background: var(--accent-gold-dim); color: var(--text-main); }

/* Smooth scroll */
html { scroll-behavior: smooth; }

/* ── Entrance Animation — 克制版 ─────────────────── */
@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

/* ── T-Chat Avatar — ink seal aesthetic ─────────── */
.t-chat-avatar {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  /* Subtle antique gold ring — like a wax seal */
  box-shadow: 0 0 0 2px rgba(201,148,58,0.15), 0 2px 8px rgba(0,0,0,0.12);
}
.t-chat-avatar--user {
  background: linear-gradient(135deg, #4f7fde 0%, #2d5fb8 100%);
  color: #fff;
}
.t-chat-avatar--assistant {
  background: linear-gradient(135deg, #fbf4e3 0%, #f0d89a 100%);
  color: #c9943a;
}

/* ── Report Body — ledger rule styling ────────────── */
.report-body h1 {
  font-family: var(--font-display);
  font-size: 20px; font-weight: 700;
  margin: 24px 0 12px;
  color: var(--ledger-ink);
  border-bottom: 2px solid var(--ledger-rule);
  padding-bottom: 8px;
  letter-spacing: -0.2px;
}
.report-body h2 {
  font-family: var(--font-display);
  font-size: 17px; font-weight: 700;
  margin: 20px 0 10px;
  color: var(--ledger-ink);
  border-bottom: 1px solid var(--ledger-rule);
  padding-bottom: 6px;
}
.report-body h3 {
  font-size: 15px; font-weight: 700;
  margin: 16px 0 8px;
}
.report-body p { margin: 0 0 12px; }
.report-body ul, .report-body ol { padding-left: 20px; margin: 8px 0; }
.report-body li { margin: 5px 0; }
.report-body strong { font-weight: 700; }
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
  border: 1px solid rgba(184,134,11,0.2);
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
</style>
