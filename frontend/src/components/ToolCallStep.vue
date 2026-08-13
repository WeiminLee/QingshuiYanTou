<template>
  <div class="tool-call-step" :class="`tool-call-step--${toolCall.status}`">
    <div
      class="tool-call-header"
      role="button"
      tabindex="0"
      :aria-expanded="expanded"
      @click="toggleExpand"
      @keydown.enter.prevent="toggleExpand"
      @keydown.space.prevent="toggleExpand"
    >
      <component :is="toolIcon" class="tool-icon" :size="15" :stroke-width="1.6" />
      <span class="tool-name">{{ normalizeToolName(toolCall.name) }}</span>
      <span v-if="toolCall.duration_ms != null" class="tool-duration">
        {{ formatDuration(toolCall.duration_ms) }}
      </span>
      <span class="tool-status" :class="`tool-status--${toolCall.status}`">
        <span v-if="toolCall.status === 'pending'" class="badge-shimmer">等待</span>
        <span v-else-if="toolCall.status === 'running'" class="badge-running">
          <span class="spinner" />
          执行中
        </span>
        <span v-else-if="toolCall.status === 'done'" class="badge-done">
          <Check :size="11" :stroke-width="1.6" />
          完成
        </span>
        <span v-else-if="toolCall.status === 'error'" class="badge-error">
          <X :size="11" :stroke-width="1.6" />
          失败
        </span>
      </span>
      <span
        v-if="toolCall.result"
        class="expand-arrow"
        :class="{ 'expand-arrow--expanded': expanded }"
      >
        <ChevronDown :size="12" :stroke-width="1.6" />
      </span>
    </div>
    <div v-if="!expanded && (toolCall.preview || toolCall.result)" class="tool-result-preview">
      {{ collapsedPreviewText }}
    </div>
    <Transition name="expand-slide">
      <div v-if="expanded" class="tool-call-detail">
        <div v-if="toolCall.args && Object.keys(toolCall.args).length > 0" class="tool-args">
          <div class="detail-label">参数</div>
          <div class="detail-content">{{ formatToolArgs(toolCall.args) }}</div>
        </div>
        <div v-if="toolCall.result" class="tool-result-full">
          <div class="detail-label">结果</div>
          <div class="detail-content">{{ toolCall.result }}</div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { Check, X, ChevronDown } from "lucide-vue-next";
import type { ToolCallItem } from "@/types/chat";
import {
  normalizeToolName,
  getToolIcon,
  formatDuration,
  formatToolArgs,
} from "@/utils/toolHelpers";

const props = defineProps<{
  toolCall: ToolCallItem;
}>();

const expanded = ref(false);

const toolIcon = computed(() => getToolIcon(props.toolCall.name));

const PREVIEW_MAX_LENGTH = 80;

const collapsedPreviewText = computed(() => {
  const preview = props.toolCall.preview;
  if (preview) return preview;
  if (!props.toolCall.result) return "";
  const result = props.toolCall.result;
  return result.length > PREVIEW_MAX_LENGTH ? result.slice(0, PREVIEW_MAX_LENGTH) + "..." : result;
});

function toggleExpand() {
  if (props.toolCall.result) {
    expanded.value = !expanded.value;
  }
}
</script>

<style scoped>
/* open-webui 极简工具调用：无盒子，整行 hover，状态用小徽章，展开面板 gray-50 */
.tool-call-step {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-family: var(--ow-font);
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 5px 8px;
  margin-left: -8px;
  border-radius: var(--ow-radius-xs);
  transition: background 0.15s;
}

.tool-call-header:hover {
  background: var(--ow-hover);
}

.tool-icon {
  line-height: 1;
  flex-shrink: 0;
  color: var(--ow-text-2);
}

.tool-name {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--ow-text);
  flex: 1;
}

.tool-duration {
  font-size: 12px;
  color: var(--ow-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.tool-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 500;
}

/* pending：灰字微光 */
.badge-shimmer {
  display: inline-block;
  color: var(--ow-text-3);
  animation: shimmer-fade 1.4s ease-in-out infinite;
  font-size: 12px;
}

@keyframes shimmer-fade {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 1;
  }
}

/* running：sky 脉冲点 + 文字 */
.badge-running {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ow-accent);
}

.spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--ow-accent-soft);
  border-top-color: var(--ow-accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* done：灰勾 */
.badge-done {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--ow-text-3);
}

/* error：红字 */
.badge-error {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--ow-error);
}

.expand-arrow {
  display: flex;
  align-items: center;
  color: var(--ow-text-3);
  transition: transform 0.2s ease;
  transform: rotate(-90deg);
  flex-shrink: 0;
}

.expand-arrow--expanded {
  transform: rotate(0deg);
}

.tool-result-preview {
  font-size: 12.5px;
  color: var(--ow-text-2);
  line-height: 1.6;
  padding: 6px 12px;
  margin-left: 4px;
  border-left: 2px solid var(--ow-border-strong);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 80px;
  overflow-y: auto;
}

.tool-call-detail {
  padding: 4px 0 2px;
  margin-left: 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ow-text-3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.detail-content {
  font-size: 12.5px;
  color: var(--ow-text-2);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
  padding: 10px 12px;
  background: var(--ow-surface);
  border: 1px solid var(--ow-border);
  border-radius: var(--ow-radius-sm);
  font-family: var(--ow-font-mono);
}

.tool-args {
  margin-bottom: 0;
}

.expand-slide-enter-active,
.expand-slide-leave-active {
  transition:
    max-height 0.28s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.2s ease;
  overflow: hidden;
}

.expand-slide-enter-from,
.expand-slide-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-slide-enter-to,
.expand-slide-leave-from {
  opacity: 1;
  max-height: 320px;
}

.tool-call-header:focus-visible {
  outline: 2px solid var(--ow-accent);
  outline-offset: 2px;
}
</style>
