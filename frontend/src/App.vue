<template>
  <div id="app">
    <router-view />
  </div>
</template>

<script setup>
</script>

<style>
/* ── Design Tokens ─────────────────────────────────────── */
:root {
  /* Deep sidebar palette */
  --bg-sidebar:     #1e1b18;
  --bg-sidebar-2:   #2a2520;
  --bg-sidebar-3:   #363129;
  --border-sidebar: rgba(255,255,255,0.08);
  --text-sidebar:   #a09888;
  --text-sidebar-muted: #6a6258;
  --text-sidebar-hi:  #d8d0c0;
  --accent-gold:    #e8a317;
  --accent-gold-dim: rgba(232,163,23,0.12);
  --accent-blue:    #3b6fd4;
  --accent-blue-dim: rgba(59,111,212,0.12);
  --accent-blue-deep: #2d5fb8;

  /* Light main area */
  --bg-main:       #f5f3ef;
  --bg-main-card:   #ffffff;
  --bg-main-raised: #faf9f6;
  --border-light:   rgba(0,0,0,0.07);
  --border-light-2: rgba(0,0,0,0.10);
  --text-main:     #1a1f2e;
  --text-main-2:   #4a5068;
  --text-main-3:   #8892a8;

  /* Status */
  --status-success: #2d9e6c;
  --status-running: #3b6fd4;
  --status-error:   #d44d4d;

  /* Fonts */
  --font-display: 'Noto Serif SC', 'Source Serif 4', Georgia, serif;
  --font-ui:      'DM Sans', 'Noto Sans SC', -apple-system, sans-serif;
  --font-mono:    'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
}

/* ── Global Reset ──────────────────────────────────────── */
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

html { font-size: 16px; }

body {
  font-family: var(--font-ui);
  background: var(--bg-main);
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

/* Entrance animations */
@keyframes fade-up {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes slide-right {
  from { opacity: 0; transform: translateX(-8px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes gold-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(232,163,23,0.3); }
  50%       { box-shadow: 0 0 0 5px rgba(232,163,23,0); }
}
@keyframes dot-bounce {
  from { transform: translateY(0); }
  to   { transform: translateY(-3px); }
}

/* ── T-Chat Avatar ─────────────────────────────────── */
.t-chat-avatar {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.t-chat-avatar--user {
  background: linear-gradient(135deg, #4f7fde 0%, #2d5fb8 100%);
  color: #fff;
}
.t-chat-avatar--assistant {
  background: linear-gradient(135deg, #fbf4e3 0%, #f4e4bd 100%);
  color: #b8780f;
  border: 1px solid rgba(232,163,23,0.3);
}

/* ── Report Body ────────────────────────────────────── */
.report-body h1 { font-size: 20px; font-weight: 700; margin: 20px 0 12px; }
.report-body h2 { font-size: 17px; font-weight: 700; margin: 18px 0 10px; }
.report-body h3 { font-size: 15px; font-weight: 700; margin: 14px 0 8px; }
.report-body p { margin: 0 0 12px; }
.report-body ul, .report-body ol { padding-left: 20px; margin: 8px 0; }
.report-body li { margin: 5px 0; }
.report-body strong { font-weight: 700; }
.report-body code {
  background: var(--bg-main-raised);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 12.5px;
}
.report-body pre {
  background: var(--bg-sidebar);
  color: var(--text-sidebar-hi);
  padding: 14px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 12px 0;
  font-family: var(--font-mono);
  font-size: 12px;
}
.report-body blockquote {
  border-left: 3px solid var(--accent-gold);
  padding: 8px 14px;
  background: var(--accent-gold-dim);
  border-radius: 0 6px 6px 0;
  margin: 14px 0;
}
</style>
