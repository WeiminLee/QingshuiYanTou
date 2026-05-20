<template>
  <div class="welcome">
    <div class="welcome-inner">
      <div class="welcome-product-name">观仓</div>

      <div class="welcome-ornament">
        <svg width="64" height="2" viewBox="0 0 64 2">
          <line x1="0" y1="1" x2="64" y2="1" stroke="#e8a317" stroke-width="1" stroke-dasharray="4 4"/>
        </svg>
      </div>

      <p class="welcome-greeting">{{ greetingText }}</p>

      <h1 class="welcome-heading">全域观市，智能管仓</h1>

      <p class="welcome-sub">
        基于全市场资讯与智能分析，为您的投资研究提供深度洞察
      </p>

      <div class="quick-grid">
        <button
          v-for="q in quickQuestions"
          :key="q"
          class="quick-chip"
          @click="$emit('select', q)"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M6 1v10M1 6h10" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
          </svg>
          {{ q }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  greetingText: string
  quickQuestions: string[]
}>()

defineEmits<{
  select: [question: string]
}>()
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
  animation: fade-up 0.5s ease both;
  transform: translateY(-20px);
}

.welcome-product-name {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  color: var(--accent-gold);
  margin-bottom: 16px;
  letter-spacing: 2px;
}

.welcome-ornament {
  display: flex;
  justify-content: center;
  margin-bottom: 28px;
  opacity: 0.6;
}

.welcome-greeting {
  font-family: var(--font-ui);
  font-size: 15px;
  color: var(--text-main-3);
  margin-bottom: 12px;
  letter-spacing: 0.5px;
}

.welcome-heading {
  font-family: var(--font-display);
  font-size: clamp(28px, 4vw, 40px);
  font-weight: 700;
  color: var(--text-main);
  line-height: 1.3;
  margin-bottom: 16px;
  letter-spacing: -0.5px;
}

.welcome-sub {
  font-size: 15px;
  color: var(--text-main-3);
  line-height: 1.8;
  max-width: 520px;
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
  padding: 11px 16px;
  border-radius: 10px;
  border: 1px solid var(--border-light-2);
  background: var(--bg-main-card);
  color: var(--text-main-2);
  font-family: var(--font-ui);
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
  transition: all 0.2s;
  animation: fade-up 0.4s ease both;
}
.quick-chip:nth-child(1) { animation-delay: 0.1s; }
.quick-chip:nth-child(2) { animation-delay: 0.2s; }
.quick-chip:nth-child(3) { animation-delay: 0.3s; }
.quick-chip:hover {
  border-color: var(--accent-gold);
  color: var(--text-main);
  box-shadow: 0 2px 12px rgba(232,163,23,0.12);
  transform: translateY(-1px);
}
.quick-chip svg { color: var(--accent-gold); flex-shrink: 0; }

@keyframes fade-up {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
