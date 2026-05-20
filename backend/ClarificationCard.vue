<template>
  <div class="clarification-card">
    <div class="clarification-header">
      <HelpCircle :size="18" class="clarification-icon" />
      <span class="clarification-title">请选择</span>
    </div>

    <div v-for="(q, qIdx) in questions" :key="qIdx" class="question-item">
      <div class="question-text">{{ q.question }}</div>
      <div v-if="q.header" class="question-header">{{ q.header }}</div>

      <div class="options-list">
        <button
          v-for="(option, oIdx) in q.options"
          :key="oIdx"
          class="option-btn"
          :class="{ selected: selectedOptions[qIdx] === oIdx }"
          @click="selectOption(qIdx, oIdx, option)"
        >
          <div class="option-label">{{ option.label }}</div>
          <div v-if="option.description" class="option-desc">{{ option.description }}</div>
        </button>
      </div>

      <div v-if="q.multiSelect && selectedOptions[qIdx] !== undefined" class="multi-hint">
        已选择，可继续选择或直接发送
      </div>
    </div>

    <div class="action-bar">
      <el-input
        v-model="customInput"
        type="textarea"
        :rows="2"
        placeholder="或者直接输入您的回答..."
        class="custom-input"
      />
      <el-button type="primary" @click="submitAnswer" :disabled="!canSubmit">
        发送
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { HelpCircle } from 'lucide-vue-next'
import { ElInput, ElButton } from 'element-plus'

interface Option {
  label: string
  description?: string
  preview?: string
}

interface Question {
  question: string
  header?: string
  options: Option[]
  multiSelect?: boolean
}

const props = defineProps<{
  questions: Question[]
}>()

const emit = defineEmits<{
  (e: 'answer', answer: string): void
}>()

const selectedOptions = ref<Record<number, number | null>>({})
const customInput = ref('')

const canSubmit = computed(() => {
  return customInput.value.trim() || Object.values(selectedOptions.value).some(v => v !== null && v !== undefined)
})

function selectOption(qIdx: number, oIdx: number, option: Option) {
  const q = props.questions[qIdx]
  if (q.multiSelect) {
    if (selectedOptions.value[qIdx] === oIdx) {
      selectedOptions.value[qIdx] = null
    } else {
      selectedOptions.value[qIdx] = oIdx
    }
  } else {
    selectedOptions.value[qIdx] = oIdx
    emit('answer', option.label)
  }
}

function submitAnswer() {
  if (customInput.value.trim()) {
    emit('answer', customInput.value.trim())
    return
  }

  const answers: string[] = []
  for (const [qIdx, oIdx] of Object.entries(selectedOptions.value)) {
    if (oIdx !== null && oIdx !== undefined) {
      const option = props.questions[Number(qIdx)]?.options[oIdx]
      if (option) {
        answers.push(option.label)
      }
    }
  }

  if (answers.length > 0) {
    emit('answer', answers.join(', '))
  }
}
</script>

<style scoped>
.clarification-card {
  background: var(--bg-main-card);
  border: 1px solid var(--border-light-2);
  border-radius: 12px;
  padding: 16px;
  margin: 12px 0;
  max-width: 500px;
}

.clarification-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.clarification-icon {
  color: var(--accent-blue);
}

.clarification-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-main);
}

.question-item {
  margin-bottom: 16px;
}

.question-text {
  font-size: 14px;
  color: var(--text-main);
  margin-bottom: 8px;
  line-height: 1.5;
}

.question-header {
  font-size: 11px;
  color: var(--accent-blue);
  background: var(--accent-blue-dim);
  padding: 2px 8px;
  border-radius: 4px;
  display: inline-block;
  margin-bottom: 10px;
}

.options-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.option-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 10px 14px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-main-raised);
  cursor: pointer;
  transition: all 0.18s ease;
  text-align: left;
}

.option-btn:hover {
  border-color: var(--accent-blue);
  background: rgba(59, 111, 212, 0.04);
}

.option-btn.selected {
  border-color: var(--accent-blue);
  background: var(--accent-blue-dim);
}

.option-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-main);
}

.option-desc {
  font-size: 11px;
  color: var(--text-main-3);
  margin-top: 2px;
}

.multi-hint {
  font-size: 11px;
  color: var(--text-main-3);
  margin-top: 6px;
}

.action-bar {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  align-items: flex-end;
}

.custom-input {
  flex: 1;
}
</style>
