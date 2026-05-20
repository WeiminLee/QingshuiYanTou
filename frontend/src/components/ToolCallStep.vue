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
      <span v-if="toolCall.result" class="expand-arrow" :class="{ 'expand-arrow--expanded': expanded }">
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
import { ref, computed } from 'vue'
import { Check, X, ChevronDown } from 'lucide-vue-next'
import type { ToolCallItem } from '@/types/chat'
import { normalizeToolName, getToolIcon, formatDuration, formatToolArgs } from '@/utils/toolHelpers'

const props = defineProps<{
  toolCall: ToolCallItem
}>()

const expanded = ref(false)

const toolIcon = computed(() => getToolIcon(props.toolCall.name))

const PREVIEW_MAX_LENGTH = 80

const collapsedPreviewText = computed(() => {
  const preview = props.toolCall.preview
  if (preview) return preview
  if (!props.toolCall.result) return ''
  const result = props.toolCall.result
  return result.length > PREVIEW_MAX_LENGTH
    ? result.slice(0, PREVIEW_MAX_LENGTH) + '...'
    : result
})

function toggleExpand() {
  if (props.toolCall.result) {
    expanded.value = !expanded.value
  }
}
</script>

<style scoped>
.tool-call-step {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid var(--border-light);
  background: var(--bg-main-card);
  transition: border-color 0.2s;
}

.tool-call-step--running {
  border-color: var(--accent-blue);
}

.tool-call-step--done {
  border-color: var(--status-success);
}

.tool-call-step--error {
  border-color: var(--status-error);
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.tool-icon {
  line-height: 1;
  flex-shrink: 0;
  color: var(--text-main-2);
}

.tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
  flex: 1;
}

.tool-duration {
  font-size: 11px;
  color: var(--status-success);
  background: rgba(45,158,108,0.08);
  padding: 1px 6px;
  border-radius: 8px;
  font-family: var(--font-mono);
  min-width: 40px;
  text-align: center;
}

.tool-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;
}

.badge-shimmer {
  display: inline-block;
  background: linear-gradient(90deg, #909399 0%, #e0e0e0 40%, #909399 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shimmer-badge 1.4s ease-in-out infinite;
  font-size: 12px;
  font-weight: 500;
}

@keyframes shimmer-badge {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.badge-running {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: rgba(59,111,212,0.1);
  color: var(--accent-blue);
  padding: 2px 8px;
  border-radius: 10px;
}

.spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 1.5px solid rgba(59,111,212,0.3);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.badge-done {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: rgba(45,158,108,0.1);
  color: var(--status-success);
  padding: 2px 8px;
  border-radius: 10px;
}

.badge-error {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: rgba(212,77,77,0.1);
  color: var(--status-error);
  padding: 2px 8px;
  border-radius: 10px;
}

.expand-arrow {
  display: flex;
  align-items: center;
  color: var(--text-main-3);
  transition: transform 0.2s ease;
  transform: rotate(-90deg);
  flex-shrink: 0;
}

.expand-arrow--expanded {
  transform: rotate(0deg);
}

.tool-result-preview {
  font-size: 12px;
  color: var(--text-main-2);
  line-height: 1.5;
  padding: 6px 10px;
  background: var(--bg-main-raised);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 80px;
  overflow-y: auto;
}

.tool-call-detail {
  padding: 8px 0 2px;
  border-top: 1px solid var(--border-light);
}

.detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-main-3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.detail-content {
  font-size: 12px;
  color: var(--text-main-2);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  padding: 6px 10px;
  background: var(--bg-main-raised);
  border-radius: 6px;
}

.tool-args {
  margin-bottom: 8px;
}

.expand-slide-enter-active,
.expand-slide-leave-active {
  transition: all 0.2s ease;
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
  max-height: 300px;
}

.tool-call-header:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: 2px;
  border-radius: inherit;
}
</style>
