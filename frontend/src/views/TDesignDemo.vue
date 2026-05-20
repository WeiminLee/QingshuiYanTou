<template>
  <div class="tdesign-demo">
    <h2>TDesign Chat Streaming Test</h2>

    <div class="demo-section">
      <h3>1. Thinking Block (Collapse/Expand)</h3>
      <t-chat-message avatar="https://tdesign.gtimg.com/site/avatar.jpg" name="AI Assistant">
        <t-chat-thinking
          :collapsed="thinkingCollapsed"
          :status="thinkingStatus"
          :content="thinkingContent"
        />
      </t-chat-message>
      <button @click="toggleCollapse">Toggle Collapse</button>
      <span>Status: {{ thinkingStatus }}</span>
    </div>

    <div class="demo-section">
      <h3>2. Streaming Test (Incremental Update)</h3>
      <t-chat-message avatar="https://tdesign.gtimg.com/site/avatar.jpg" name="AI Assistant">
        <t-chat-thinking
          :collapsed="false"
          status="loading"
          :content="streamingContent"
        />
      </t-chat-message>
      <button @click="startStreaming">Start Streaming</button>
      <button @click="resetStreaming">Reset</button>
      <div class="log">Updates: {{ updateCount }}</div>
    </div>

    <div class="demo-section">
      <h3>3. Action Buttons</h3>
      <t-chat-message avatar="https://tdesign.gtimg.com/site/avatar.jpg" name="AI Assistant">
        <t-chat-content content="请选择您关注的方向：" />
        <t-chat-actionbar>
          <t-chat-action
            v-for="(action, index) in actions"
            :key="index"
            :label="action.label"
            @click="handleAction(action)"
          />
        </t-chat-actionbar>
      </t-chat-message>
      <button @click="addOption">Add Option</button>
      <div class="log">Selected: {{ selectedAction }}</div>
    </div>

    <div class="demo-section">
      <h3>4. Real SSE Test (via useChatSession)</h3>
      <input v-model="testQuestion" placeholder="输入问题" />
      <button @click="startRealSSE">Connect to Backend</button>
      <div class="sse-messages">
        <div v-for="msg in messages" :key="msg.id" class="sse-msg">
          <strong>{{ msg.role }}:</strong> {{ msg.content || msg.thinkingContent ? '[思考中...]' : '' }}
        </div>
        <div v-if="isLoading" class="sse-loading">⏳ 等待响应...</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useChatSession } from '@/composables/useChatSession'

// Test 1: Collapse/Expand
const thinkingCollapsed = ref(false)
const thinkingStatus = ref('done')
const thinkingContent = ref('这是一个静态思考内容，用于测试折叠/展开功能。')

function toggleCollapse() {
  thinkingCollapsed.value = !thinkingCollapsed.value
}

// Test 2: Streaming
const streamingContent = ref('')
const updateCount = ref(0)

async function startStreaming() {
  streamingContent.value = ''
  updateCount.value = 0

  const chunks = [
    '分析中...',
    '\n正在检索数据...',
    '\n发现 3 条相关信息',
    '\n正在生成回答...',
    '\n完成！'
  ]

  for (const chunk of chunks) {
    streamingContent.value += chunk
    updateCount.value++
    await new Promise(resolve => setTimeout(resolve, 500))
  }
}

function resetStreaming() {
  streamingContent.value = ''
  updateCount.value = 0
}

// Test 3: Actions
const actions = ref([
  { label: '光模块', value: 'optical-module' },
  { label: '服务器', value: 'server' },
  { label: '芯片', value: 'chip' }
])
const selectedAction = ref('')

function addOption() {
  const newOption = { label: `选项 ${actions.value.length + 1}`, value: `option-${actions.value.length + 1}` }
  actions.value.push(newOption)
}

function handleAction(action) {
  selectedAction.value = action.label
}

// Test 4: Real SSE via useChatSession
const testQuestion = ref('AI算力链条还能投吗？')

const {
  messages, isLoading, error, thinkingCollapsed: thinkingCollapsedSession,
  sendMessage, stop, reset
} = useChatSession()

async function startRealSSE() {
  await sendMessage(testQuestion.value)
}
</script>

<style scoped>
.tdesign-demo {
  max-width: 900px;
  margin: 40px auto;
  padding: 20px;
}

h2 {
  color: #1a1a2e;
  margin-bottom: 30px;
}

.demo-section {
  margin-bottom: 40px;
  padding: 20px;
  background: #f8f9fa;
  border-radius: 12px;
  border: 1px solid #e0e0e0;
}

h3 {
  color: #2a2a3e;
  margin-bottom: 15px;
}

button {
  margin: 10px 10px 10px 0;
  padding: 10px 20px;
  background: #e8a317;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

button:hover {
  background: #d4920f;
}

input {
  padding: 10px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  font-size: 14px;
  width: 300px;
  margin-right: 10px;
}

.log {
  margin-top: 10px;
  padding: 10px;
  background: white;
  border-radius: 6px;
  font-family: monospace;
  font-size: 12px;
  color: #666;
}

.sse-messages {
  margin-top: 12px;
  padding: 12px;
  background: white;
  border-radius: 8px;
  border: 1px solid #e0e0e0;
  max-height: 200px;
  overflow-y: auto;
}

.sse-msg {
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
}

.sse-msg:last-child {
  border-bottom: none;
}

.sse-loading {
  padding: 8px;
  color: #3b6fd4;
  font-size: 13px;
}
</style>
