<template>
  <div class="spike-container">
    <h3>TDesign Chat Spike — Slot Validation</h3>

    <ChatList
      :data="chatData"
      :is-stream-load="isStreaming"
      layout="both"
      auto-scroll
    >
      <!-- 自定义 reasoning slot -->
      <template #reasoning="{ item }">
        <div class="spike-reasoning" v-if="item.reasoning">
          <div class="reasoning-header" @click="toggleReasoning(item)">
            <span>🧐 思考过程</span>
            <span v-if="item.reasoning.collapsed">▶</span>
            <span v-else>▼</span>
          </div>
          <div v-if="!item.reasoning.collapsed" class="reasoning-body">
            {{ item.reasoning.content }}
          </div>
        </div>
      </template>

      <!-- 自定义 content slot — 嵌入 ToolCallStep -->
      <template #content="{ item }">
        <div v-if="item.role === 'assistant' && item.toolCalls?.length" class="spike-tools">
          <div v-for="tc in item.toolCalls" :key="tc.id" class="spike-tool-step">
            <span class="tool-icon">🔧</span>
            <span class="tool-name">{{ tc.name }}</span>
            <span :class="`tool-status tool-status--${tc.status}`">{{ tc.status }}</span>
          </div>
        </div>
        <div v-if="item.content" class="spike-content" v-html="item.content" />
      </template>
    </ChatList>

    <ChatSender
      v-model="inputText"
      :loading="isStreaming"
      placeholder="输入问题测试..."
      @send="handleSend"
      @stop="handleStop"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ChatList, ChatSender } from '@tdesign-vue-next/chat'
import '@tdesign-vue-next/chat/es/style/index.css'

const inputText = ref('')
const isStreaming = ref(false)

interface SpikeChatItem {
  role: 'user' | 'assistant'
  avatar?: string
  name?: string
  datetime?: string
  content?: string
  reasoning?: { content: string; collapsed: boolean }
  toolCalls?: Array<{ id: string; name: string; status: string }>
}

const chatData = ref<SpikeChatItem[]>([
  {
    role: 'user',
    avatar: '',
    name: '你',
    datetime: '10:30',
    content: 'AI算力链条还能投吗？',
  },
  {
    role: 'assistant',
    avatar: '',
    name: '观仓 AI',
    datetime: '10:30',
    reasoning: {
      content: '用户询问AI算力链条的投资机会，我需要先获取概念板块热度、市场宽度数据，然后搜索最新资讯和研报观点，最后综合分析给出建议。',
      collapsed: true,
    },
    toolCalls: [
      { id: '1', name: 'get_concept_hot', status: 'done' },
      { id: '2', name: 'get_market_breadth', status: 'error' },
      { id: '3', name: 'tavily_search', status: 'done' },
      { id: '4', name: 'get_research_report', status: 'done' },
    ],
    content: '<p>基于当前市场数据分析，AI算力链条整体仍具投资价值，但需关注以下要点：</p><ul><li>光模块板块近期涨幅较大，注意短期回调风险</li><li>液冷服务器需求持续增长</li><li>建议关注估值合理的细分龙头</li></ul>',
  },
])

function toggleReasoning(item: SpikeChatItem) {
  if (item.reasoning) {
    item.reasoning.collapsed = !item.reasoning.collapsed
  }
}

function handleSend(value: string) {
  chatData.value = [
    ...chatData.value,
    { role: 'user' as const, content: value, datetime: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) },
  ]
  isStreaming.value = true
  setTimeout(() => {
    chatData.value = [
      ...chatData.value,
      { role: 'assistant' as const, content: `<p>收到：${value}</p>`, datetime: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) },
    ]
    isStreaming.value = false
  }, 2000)
}

function handleStop() {
  isStreaming.value = false
}
</script>

<style scoped>
.spike-container {
  max-width: 800px;
  margin: 20px auto;
  padding: 16px;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  background: var(--bg-main-card);
}

h3 {
  margin-bottom: 16px;
  color: var(--text-main);
}

.spike-reasoning {
  margin-bottom: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  overflow: hidden;
}

.reasoning-header {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-main-raised);
  cursor: pointer;
  font-size: 13px;
  color: var(--text-main-2);
}

.reasoning-body {
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-main-2);
  background: var(--bg-main-card);
}

.spike-tools {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}

.spike-tool-step {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 6px;
  background: var(--bg-main-raised);
  font-size: 12px;
}

.tool-name {
  font-weight: 600;
  color: var(--text-main);
}

.tool-status {
  margin-left: auto;
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 11px;
}

.tool-status--done {
  background: rgba(45, 158, 108, 0.1);
  color: var(--status-success);
}

.tool-status--error {
  background: rgba(212, 77, 77, 0.1);
  color: var(--status-error);
}

.tool-status--running {
  background: rgba(59, 111, 212, 0.1);
  color: var(--accent-blue);
}

.spike-content {
  font-size: 14px;
  line-height: 1.6;
}

.spike-content :deep(p) {
  margin: 4px 0;
}

.spike-content :deep(li) {
  margin: 2px 0;
}
</style>
