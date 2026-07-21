<template>
  <div class="welcome">
    <div class="welcome-inner">
      <div class="welcome-product-name">观仓</div>

      <p class="welcome-greeting">{{ greetingText }}</p>

      <h1 class="welcome-heading">全域观市，智能管仓</h1>

      <p class="welcome-sub">基于全市场资讯与智能分析，为您的投资研究提供深度洞察</p>

      <div class="quick-grid">
        <button v-for="q in quickQuestions" :key="q" class="quick-chip" @click="$emit('select', q)">
          {{ q }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  greetingText: string;
  quickQuestions: string[];
}>();

defineEmits<{
  select: [question: string];
}>();
</script>

<style scoped>
/* ── Welcome ──────────────────────────────────────────── */
.welcome {
  min-height: calc(100vh - 100px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 40px;
}

.welcome-inner {
  max-width: 620px;
  width: 100%;
  text-align: center;
  animation: fade-in 0.5s ease both;
}

@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.welcome-product-name {
  font-family: var(--ow-font);
  font-size: 44px;
  font-weight: 600;
  color: var(--ow-text);
  margin-bottom: 20px;
  letter-spacing: 4px;
  animation: fade-in 0.5s ease both;
}

.welcome-greeting {
  font-family: var(--ow-font);
  font-size: 15px;
  color: var(--ow-text-3);
  margin-bottom: 10px;
}

.welcome-heading {
  font-family: var(--ow-font);
  font-size: clamp(26px, 4vw, 36px);
  font-weight: 600;
  color: var(--ow-text);
  line-height: 1.3;
  margin-bottom: 14px;
  letter-spacing: -0.02em;
}

.welcome-sub {
  font-family: var(--ow-font);
  font-size: 15px;
  color: var(--ow-text-2);
  line-height: 1.7;
  max-width: 480px;
  margin: 0 auto 36px;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  max-width: 560px;
  margin: 0 auto;
}

.quick-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 13px 18px;
  border-radius: var(--ow-radius-sm);
  border: 1px solid var(--ow-border);
  background: var(--ow-bg);
  color: var(--ow-text-2);
  font-family: var(--ow-font);
  font-size: 14px;
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.15s,
    background 0.15s,
    color 0.15s;
  animation: fade-in 0.4s ease both;
}
.quick-chip:nth-child(1) {
  animation-delay: 0.05s;
}
.quick-chip:nth-child(2) {
  animation-delay: 0.1s;
}
.quick-chip:nth-child(3) {
  animation-delay: 0.15s;
}
.quick-chip:hover {
  border-color: var(--ow-border-strong);
  color: var(--ow-text);
  background: var(--ow-surface);
}
</style>
