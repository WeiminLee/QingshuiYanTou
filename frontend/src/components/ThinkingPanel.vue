<template>
  <div class="thinking-panel" :class="{ 'thinking-panel--collapsed': isCollapsed }">
    <div
      class="thinking-header"
      role="button"
      tabindex="0"
      :aria-expanded="!isCollapsed"
      @click="toggleCollapse"
      @keydown.enter.prevent="toggleCollapse"
      @keydown.space.prevent="toggleCollapse"
    >
      <Brain class="thinking-icon" :size="15" :stroke-width="1.6" />
      <span class="thinking-label">
        <template v-if="loading">思考中...</template>
        <template v-else>思考完成</template>
      </span>
      <span v-if="elapsedText" class="thinking-elapsed">{{ elapsedText }}</span>
      <span class="thinking-arrow" :class="{ 'thinking-arrow--expanded': !isCollapsed }">
        <ChevronDown :size="12" :stroke-width="1.6" />
      </span>
    </div>
    <Transition name="thinking-collapse">
      <div v-if="!isCollapsed" class="thinking-body">
        <div class="thinking-content" v-html="sanitize(filteredContent)"></div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from "vue";
import { Brain, ChevronDown } from "lucide-vue-next";
import { sanitize } from "@/utils/sanitize.js";
import { formatDuration } from "@/utils/toolHelpers";

const props = withDefaults(
  defineProps<{
    content: string;
    loading?: boolean;
    collapsed?: boolean;
  }>(),
  {
    loading: false,
    collapsed: false,
  },
);

const AUTO_COLLAPSE_DELAY_MS = 1000; // P23-B: locked by CONTEXT, do not make configurable

const startTime = ref<number | null>(null);
const elapsedMs = ref(0);
const hasAutoCollapsed = ref(false);
let elapsedTimer: ReturnType<typeof setInterval> | null = null;
let collapseTimer: ReturnType<typeof setTimeout> | null = null;

const isCollapsed = computed(() => props.collapsed || hasAutoCollapsed.value);

const elapsedText = computed(() => {
  if (elapsedMs.value <= 0 && !startTime.value) return "";
  return formatDuration(elapsedMs.value);
});

const filteredContent = computed(() => {
  return props.content.replace(/\[ASK_CLARIFICATION\][\s\S]*$/g, "").trim();
});

watch(
  () => props.content,
  (newVal) => {
    if (newVal && !startTime.value) {
      startTime.value = Date.now();
      startElapsedTimer();
    }
  },
);

watch(
  () => props.loading,
  (newLoading, oldLoading) => {
    if (oldLoading && !newLoading) {
      stopElapsedTimer();
      if (startTime.value) {
        elapsedMs.value = Date.now() - startTime.value;
      }
      if (collapseTimer) clearTimeout(collapseTimer);
      collapseTimer = setTimeout(() => {
        hasAutoCollapsed.value = true;
      }, AUTO_COLLAPSE_DELAY_MS);
    }
  },
);

function startElapsedTimer() {
  if (elapsedTimer) return;
  elapsedTimer = setInterval(() => {
    if (startTime.value) {
      elapsedMs.value = Date.now() - startTime.value;
    }
  }, 200);
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

function toggleCollapse() {
  if (!props.loading) {
    hasAutoCollapsed.value = !hasAutoCollapsed.value;
  }
}

onUnmounted(() => {
  stopElapsedTimer();
  if (collapseTimer) clearTimeout(collapseTimer);
});
</script>

<style scoped>
.thinking-panel {
  border-radius: 4px;
  border: 1px solid var(--ledger-rule);
  background: var(--ledger-entry);
  overflow: hidden;
  transition: border-color 0.2s;
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}

.thinking-header:hover {
  background: var(--ledger-entry);
}

.thinking-icon {
  line-height: 1;
  flex-shrink: 0;
  color: var(--ledger-gold);
}

.thinking-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ledger-ink);
  flex: 1;
}

.thinking-elapsed {
  font-size: 11px;
  font-weight: 600;
  color: var(--ledger-blue);
  background: rgba(59, 91, 219, 0.08);
  padding: 1px 8px;
  border-radius: 4px;
  font-family: var(--font-mono);
  white-space: nowrap;
  letter-spacing: 0.02em;
}

.thinking-arrow {
  display: flex;
  align-items: center;
  color: var(--ledger-gray);
  transition: transform 0.2s ease;
  transform: rotate(-90deg);
  flex-shrink: 0;
}

.thinking-arrow--expanded {
  transform: rotate(0deg);
}

.thinking-body {
  border-top: 1px solid var(--ledger-rule);
  padding: 10px 14px;
}

.thinking-content {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-main-2);
  max-height: 300px;
  overflow-y: auto;
  padding: 4px 0;
}

.thinking-content :deep(p) {
  margin: 4px 0;
}

.thinking-content :deep(strong) {
  color: var(--ledger-ink);
  font-weight: 600;
}

.thinking-collapse-enter-active,
.thinking-collapse-leave-active {
  transition:
    max-height 0.28s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.2s ease-out;
  overflow: hidden;
}

.thinking-collapse-enter-from,
.thinking-collapse-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.thinking-collapse-enter-to,
.thinking-collapse-leave-from {
  opacity: 1;
  max-height: 320px;
}

.thinking-header:focus-visible {
  outline: 2px solid var(--ledger-blue);
  outline-offset: 2px;
  border-radius: inherit;
}
</style>
