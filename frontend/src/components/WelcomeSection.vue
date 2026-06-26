<template>
  <div class="welcome">
    <div class="welcome-inner">
      <div class="welcome-product-name">观仓</div>

      <div class="welcome-ornament">
        <svg width="200" height="20" viewBox="0 0 200 20" fill="none">
          <!-- 羽毛笔分隔线 -->
          <line x1="0" y1="10" x2="80" y2="10" stroke="#D4CFC4" stroke-width="1" />
          <!-- 羽毛 -->
          <path d="M85 10 Q90 5 95 8 Q92 10 95 12 Q90 15 85 10Z" fill="#B8860B" opacity="0.6" />
          <path d="M95 10 L100 10" stroke="#B8860B" stroke-width="1" />
          <line x1="105" y1="10" x2="200" y2="10" stroke="#D4CFC4" stroke-width="1" />
        </svg>
      </div>

      <p class="welcome-greeting">{{ greetingText }}</p>

      <h1 class="welcome-heading">全域观市，智能管仓</h1>

      <p class="welcome-sub">基于全市场资讯与智能分析，为您的投资研究提供深度洞察</p>

      <div class="quick-grid">
        <button v-for="q in quickQuestions" :key="q" class="quick-chip" @click="$emit('select', q)">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path
              d="M6 1v10M1 6h10"
              stroke="currentColor"
              stroke-width="1.2"
              stroke-linecap="round"
            />
          </svg>
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
  font-family: var(--font-display);
  font-size: 48px;
  font-weight: 700;
  color: var(--ledger-ink);
  margin-bottom: 8px;
  letter-spacing: 8px;
  animation: fade-in 0.5s ease both;
}

.welcome-ornament {
  display: flex;
  justify-content: center;
  margin-bottom: 28px;
  opacity: 0.5;
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
  padding: 12px 18px;
  border-radius: 0;
  border: 1px solid var(--ledger-rule);
  background: var(--ledger-entry);
  color: var(--text-main-2);
  font-family: var(--font-ui);
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
  transition: all 0.2s;
  animation: fade-in 0.4s ease both;
  /* 账页标签 — 左侧打孔边 */
  position: relative;
}
.quick-chip::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  background-image: radial-gradient(circle at 50% 50%, var(--ledger-paper) 3px, transparent 4px);
  background-size: 6px 20px;
  background-repeat: repeat-y;
  background-position: center;
  border-right: 1px solid var(--ledger-rule);
}
.quick-chip:nth-child(1) {
  animation-delay: 0.1s;
}
.quick-chip:nth-child(2) {
  animation-delay: 0.2s;
}
.quick-chip:nth-child(3) {
  animation-delay: 0.3s;
}
.quick-chip:hover {
  border-color: var(--ledger-gold);
  color: var(--text-main);
  transform: rotateX(2deg) translateY(-2px);
  box-shadow: 0 4px 12px rgba(184, 134, 11, 0.12);
}
.quick-chip svg {
  color: var(--ledger-gold);
  flex-shrink: 0;
}
</style>
