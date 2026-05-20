<template>
  <div class="report-page">
    <!-- Header -->
    <div class="page-header">
      <router-link to="/" class="back-link">
        <el-icon><ArrowLeft /></el-icon>
        返回首页
      </router-link>
      <div v-if="taskId" class="task-status">
        <el-tag v-if="!isLoading && reportContent" type="success" size="small">分析完成</el-tag>
        <el-tag v-else-if="error" type="danger" size="small">分析失败</el-tag>
        <el-tag v-else-if="isLoading" type="warning" size="small">分析中...</el-tag>
      </div>
    </div>

    <!-- Question input (only when no active task) -->
    <div v-if="!taskId" class="question-section">
      <h2 class="question-title">开始投研分析</h2>
      <div class="question-input-wrapper">
        <el-input
          v-model="question"
          placeholder="输入您的问题，例如：中际旭创的竞争格局如何？"
          size="large"
          type="textarea"
          :rows="3"
          resize="none"
          @keyup.ctrl.enter="handleSend(question)"
        />
        <div class="input-actions">
          <div class="input-hints">
            <span class="hint-label">快捷问题：</span>
            <el-tag
              v-for="q in quickQuestions"
              :key="q"
              size="small"
              class="quick-tag"
              @click="question = q"
            >
              {{ q }}
            </el-tag>
          </div>
          <el-button
            type="primary"
            size="large"
            :loading="isLoading"
            :disabled="!question.trim()"
            @click="handleSend(question)"
          >
            开始分析
          </el-button>
        </div>
      </div>
    </div>

    <!-- Active chat area -->
    <div v-if="taskId" class="streaming-section">
      <ChatList
        :data="tdesignItems"
        :is-stream-load="isLoading"
        layout="both"
        auto-scroll
      >
        <template #reasoning="{ item }">
          <ThinkingPanel
            v-if="item.reasoning"
            :content="item.reasoning.content"
            :loading="false"
            :collapsed="item.reasoning.collapsed"
          />
        </template>
        <template #content="{ item }">
          <template v-if="item.role === 'assistant'">
            <template v-for="msg in messages" :key="msg.id">
              <template v-if="msg.id === item.id">
                <div v-if="msg.toolCalls && msg.toolCalls.length > 0" class="report-tool-chain">
                  <ToolCallStep
                    v-for="(tc, idx) in msg.toolCalls"
                    :key="tc.id || idx"
                    :tool-call="tc"
                  />
                </div>
              </template>
            </template>
          </template>
        </template>
        <template #avatar="{ item }">
          <div v-if="item.role === 'user'" class="t-chat-avatar t-chat-avatar--user">
            <UserRound :size="16" :stroke-width="1.8" />
          </div>
          <div v-else class="t-chat-avatar t-chat-avatar--assistant">
            <Sparkles :size="16" :stroke-width="1.8" />
          </div>
        </template>
      </ChatList>

      <!-- Final report -->
      <div v-if="reportContent" class="report-section">
        <div class="report-divider">
          <svg width="48" height="12" viewBox="0 0 48 12">
            <line x1="0" y1="6" x2="20" y2="6" stroke="#d0ccc6" stroke-width="1"/>
            <circle cx="24" cy="6" r="3" fill="none" stroke="#e8a317" stroke-width="1"/>
            <line x1="28" y1="6" x2="48" y2="6" stroke="#d0ccc6" stroke-width="1"/>
          </svg>
        </div>
        <CustomMarkdownRenderer :content="reportContent" class="report-body" />
        <div class="compliance-stamp">
          ⚠️ 本报告由清水投研系统 AI 生成，仅供投资研究参考，不构成任何投资建议
        </div>
        <div class="report-actions">
          <el-button @click="handleReset">新建分析</el-button>
          <el-button type="primary" @click="handleCopyReport">复制报告</el-button>
        </div>
      </div>

      <!-- Error -->
      <div v-if="error" class="error-card">
        <span>{{ error }}</span>
        <button class="btn-retry" @click="handleReset">重新分析</button>
      </div>
    </div>

    <!-- Chat input (sticky bottom when task active) -->
    <ChatSender
      v-if="taskId"
      v-model="inputText"
      :loading="isLoading"
      placeholder="继续追问…"
      @send="handleSend"
      @stop="stop"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { getTaskResult } from '../api/agent.js'
import { useChatSession } from '@/composables/useChatSession'
import { useTDesignAdapter } from '@/composables/useTDesignAdapter'
import { ChatList, ChatSender } from '@tdesign-vue-next/chat'
import '@tdesign-vue-next/chat/es/style/index.css'
import { Sparkles, UserRound } from 'lucide-vue-next'
import ThinkingPanel from '@/components/ThinkingPanel.vue'
import ToolCallStep from '@/components/ToolCallStep.vue'
import CustomMarkdownRenderer from '@/components/CustomMarkdownRenderer.vue'

const route = useRoute()

// Chat session (unified SSE + message state)
const {
  messages, taskId, isLoading, error, thinkingCollapsed,
  sendMessage, stop, reset
} = useChatSession()

// TDesign adapter
const { tdesignItems } = useTDesignAdapter(messages)

// Input state for ChatSender
const inputText = ref('')

// Report state (separate from chat messages — report is a final artifact)
const reportContent = ref('')
const lastTaskId = ref('')
const lastQuestion = ref('')

// Watch for stream completion → fetch final report
watch([isLoading, taskId], async ([loading, tid], oldVals) => {
  const prevLoading = oldVals?.[0] ?? false
  if (prevLoading && !loading && tid && tid !== lastTaskId.value) {
    lastTaskId.value = tid
    await fetchFinalReport(tid)
  }
})

async function fetchFinalReport(tid: string) {
  try {
    const res = await getTaskResult(tid)
    const raw = res.reportContent || res.content || ''
    if (raw) {
      reportContent.value = raw
    }
  } catch {
    // Report fetch failed — content already streamed via ChatMessageList
  }
}

// Question input state
const question = ref('')

const quickQuestions = [
  '中际旭创的竞争格局如何？',
  '光伏行业2025年景气度展望',
  '低空经济投资机会分析',
]

// Actions
function handleSend(text: string) {
  reportContent.value = ''
  lastTaskId.value = ''
  lastQuestion.value = text.trim()
  question.value = ''
  inputText.value = ''
  sendMessage(text.trim())
}

function handleReset() {
  reportContent.value = ''
  lastTaskId.value = ''
  lastQuestion.value = ''
  question.value = ''
  inputText.value = ''
  reset()
}

function handleRetry() {
  if (lastQuestion.value) {
    handleSend(lastQuestion.value)
  }
}

function handleCopyReport() {
  if (reportContent.value) {
    navigator.clipboard.writeText(reportContent.value).then(() => {
      ElMessage.success('已复制到剪贴板')
    }).catch(() => {
      ElMessage.error('复制失败')
    })
  }
}

// Init from route query
onMounted(() => {
  if (route.query.q) {
    const q = String(route.query.q)
    question.value = q
    handleSend(q)
  }
})
</script>

<style scoped>
.report-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px;
  min-height: calc(100vh - 56px);
  display: flex;
  flex-direction: column;
}

/* Header */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.back-link {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #606266;
  text-decoration: none;
  font-size: 14px;
  transition: color 0.2s;
}

.back-link:hover { color: #409eff; }

.task-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Question input */
.question-section {
  background: #fff;
  border-radius: 12px;
  padding: 32px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.question-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 16px;
}

.question-input-wrapper {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.question-input-wrapper :deep(.el-textarea__inner) {
  border-radius: 8px;
  font-size: 15px;
  line-height: 1.6;
}

.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.input-hints {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.hint-label { font-size: 13px; color: #909399; }
.quick-tag { cursor: pointer; }

/* Streaming section */
.streaming-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* t-chat slot styles (avatar styles moved to App.vue) */
.report-tool-chain {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}

/* Report section */
.report-section { display: flex; flex-direction: column; gap: 0; }

.report-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 8px 0 24px;
  opacity: 0.8;
}

.report-body { animation: fade-up 0.4s ease both; }

/* report-body styles moved to App.vue */

.compliance-stamp {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-top: 32px;
  padding: 12px 16px;
  background: #f0f9eb;
  border: 1px solid #d4edda;
  border-radius: 8px;
  font-size: 11.5px;
  color: #606260;
  line-height: 1.6;
}

.report-actions {
  margin-top: 20px;
  display: flex;
  justify-content: center;
  gap: 12px;
}

/* Error */
.error-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: #fef2f2;
  border: 1px solid rgba(212,77,77,0.2);
  border-radius: 10px;
  color: #d44d4d;
  font-size: 13px;
}

.error-card span { flex: 1; }

.btn-retry {
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid #d44d4d;
  background: transparent;
  color: #d44d4d;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.btn-retry:hover { background: #d44d4d; color: #fff; }

@keyframes fade-up {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
