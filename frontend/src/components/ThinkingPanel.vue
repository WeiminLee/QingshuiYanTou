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
      <span class="thinking-label">
        <template v-if="loading">正在思考…</template>
        <template v-else>已完成思考</template>
      </span>
      <span v-if="elapsedText" class="thinking-elapsed">{{ elapsedText }}</span>
      <span class="thinking-arrow" :class="{ 'thinking-arrow--expanded': !isCollapsed }">
        <ChevronDown :size="14" :stroke-width="2" />
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
import { ChevronDown } from "lucide-vue-next";
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
/* open-webui 极简思考折叠：无盒子，一行灰字 + chevron，展开内容左竖线 */
.thinking-panel {
  font-family: var(--ow-font);
  margin: 2px 0;
}

.thinking-header {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  margin-left: -6px;
  border-radius: var(--ow-radius-xs);
  cursor: pointer;
  user-select: none;
  color: var(--ow-text-2);
  transition:
    color 0.15s,
    background 0.15s;
}

.thinking-header:hover {
  color: var(--ow-text);
  background: var(--ow-hover);
}

.thinking-label {
  font-size: 13.5px;
  font-weight: 500;
}

.thinking-elapsed {
  font-size: 12px;
  font-weight: 400;
  color: var(--ow-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.thinking-arrow {
  display: flex;
  align-items: center;
  color: var(--ow-text-3);
  transition: transform 0.2s ease;
  transform: rotate(-90deg);
  flex-shrink: 0;
}

.thinking-arrow--expanded {
  transform: rotate(0deg);
}

.thinking-body {
  margin-top: 6px;
  padding-left: 12px;
  border-left: 2px solid var(--ow-border-strong);
}

.thinking-content {
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--ow-text-2);
  max-height: 320px;
  overflow-y: auto;
}

.thinking-content :deep(p) {
  margin: 4px 0;
}

.thinking-content :deep(strong) {
  color: var(--ow-text);
  font-weight: 600;
}

.thinking-collapse-enter-active,
.thinking-collapse-leave-active {
  transition:
    max-height 0.3s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.2s ease-out;
  overflow: hidden;
}

.thinking-collapse-enter-from,
.thinking-collapse-leave-to {
  opacity: 0;
  max-height: 0;
  margin-top: 0;
}

.thinking-collapse-enter-to,
.thinking-collapse-leave-from {
  opacity: 1;
  max-height: 340px;
}

.thinking-header:focus-visible {
  outline: 2px solid var(--ow-accent);
  outline-offset: 2px;
}
</style>
