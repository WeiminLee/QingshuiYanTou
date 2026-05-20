<template>
  <div class="stream-error-card">
    <div class="error-icon">
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
        <circle cx="9" cy="9" r="8" stroke="currentColor" stroke-width="1.5"/>
        <path d="M9 5V9.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        <circle cx="9" cy="12.5" r="0.8" fill="currentColor"/>
      </svg>
    </div>
    <div class="error-body">
      <div class="error-title">连接中断</div>
      <div class="error-message">{{ message }}</div>
    </div>
    <button v-if="retryable" class="error-retry-btn" @click="$emit('retry')">
      重试
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  message: string
  retryable?: boolean
}>()

defineEmits<{
  retry: []
}>()
</script>

<style scoped>
.stream-error-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 10px;
  border: 1px solid rgba(212,77,77,0.25);
  background: rgba(212,77,77,0.06);
}

.error-icon {
  display: flex;
  align-items: center;
  color: var(--status-error);
  flex-shrink: 0;
}

.error-body {
  flex: 1;
  min-width: 0;
}

.error-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--status-error);
}

.error-message {
  font-size: 12px;
  color: var(--text-main-2);
  margin-top: 2px;
  line-height: 1.4;
}

.error-retry-btn {
  font-size: 12px;
  font-weight: 500;
  color: var(--accent-blue);
  background: rgba(59,111,212,0.08);
  border: 1px solid rgba(59,111,212,0.2);
  border-radius: 6px;
  padding: 4px 12px;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}

.error-retry-btn:hover {
  background: rgba(59,111,212,0.15);
}

.error-retry-btn:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: 2px;
  border-radius: inherit;
}
</style>
