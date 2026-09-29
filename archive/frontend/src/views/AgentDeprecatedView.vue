<template>
  <div class="wrap">
    <h1>Agent 对话入口已切换到 dsh</h1>
    <p>
      Vue / LangChain Agent 聊天路径已退役（切到 dsh 运行时）。投研对话请使用
      <code>dsh web</code> 或 <code>dsh --profile headless</code>，并安装
      <code>plugins/qingshui</code>。
    </p>
    <ul>
      <li>本地：<code>pnpm run build:plugin && pnpm dsh plugin --profile web add ./plugins/qingshui</code></li>
      <li>启动：<code>pnpm dsh --profile web</code></li>
      <li>设计：<code>docs/superpowers/specs/2026-09-29-dsh-agent-runtime-cutover-design.md</code></li>
    </ul>
    <p class="muted">账户 / 组合 / 个股等非聊天页暂留；全切终验时整树退役。</p>
    <router-link to="/portfolio">返回组合</router-link>
  </div>
</template>

<script setup>
</script>

<style scoped>
.wrap { max-width: 720px; margin: 48px auto; padding: 0 16px; font-family: system-ui, sans-serif; line-height: 1.6; }
h1 { font-size: 1.4rem; margin-bottom: 12px; }
code { background: #f3f4f6; padding: 1px 6px; border-radius: 4px; }
.muted { color: #6b7280; font-size: 0.9rem; }
ul { padding-left: 1.2rem; }
a { color: #1d4ed8; }
</style>
