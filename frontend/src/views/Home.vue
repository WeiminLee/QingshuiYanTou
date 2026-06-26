<template>
  <div class="layout">
    <!-- ════════════════════════════════════════════════════ -->
    <!-- SIDEBAR: Deep night blue — sidebar-as-terminal aesthetic -->
    <!-- ════════════════════════════════════════════════════ -->
    <aside class="sidebar">
      <!-- Logo -->
      <div class="sidebar-logo">
        <div class="logo-mark">
          <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
            <!-- 账本图标 — 翻开的书页 -->
            <rect
              x="3"
              y="4"
              width="9"
              height="18"
              rx="1"
              stroke="#B8860B"
              stroke-width="1.2"
              fill="none"
            />
            <rect
              x="14"
              y="4"
              width="9"
              height="18"
              rx="1"
              stroke="#B8860B"
              stroke-width="1.2"
              fill="none"
            />
            <line x1="12" y1="4" x2="12" y2="22" stroke="#B8860B" stroke-width="1.2" />
            <!-- 中缝虚线 -->
            <line
              x1="12"
              y1="7"
              x2="12"
              y2="10"
              stroke="#B8860B"
              stroke-width="0.8"
              stroke-dasharray="2 2"
            />
            <line
              x1="12"
              y1="12"
              x2="12"
              y2="15"
              stroke="#B8860B"
              stroke-width="0.8"
              stroke-dasharray="2 2"
            />
            <line
              x1="12"
              y1="17"
              x2="12"
              y2="19"
              stroke="#B8860B"
              stroke-width="0.8"
              stroke-dasharray="2 2"
            />
          </svg>
        </div>
        <div class="logo-text">
          <span class="logo-name">清水投研</span>
          <span class="logo-sub">观仓 AI</span>
        </div>
      </div>

      <!-- New chat CTA -->
      <button class="btn-new-chat" @click="startNewConversation">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path
            d="M7 1v12M1 7h12"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
          />
        </svg>
        新建账目
      </button>

      <!-- History -->
      <div class="sidebar-section">
        <div class="sidebar-section-label">最近对话</div>
        <div v-if="historyLoading" class="sidebar-loading">
          <span class="loading-dots"><span /><span /><span /></span>
        </div>
        <div v-else-if="recentHistory.length === 0" class="sidebar-empty-hint">暂无记录</div>
        <div v-else class="sidebar-list">
          <button
            v-for="item in recentHistory"
            :key="item.task_id"
            class="sidebar-item"
            @click="loadHistoryTask(item)"
          >
            <svg class="item-icon" width="12" height="12" viewBox="0 0 12 12" fill="none">
              <circle cx="6" cy="6" r="5.5" stroke="currentColor" stroke-width="1" />
              <path d="M3.5 6 Q6 3 8.5 6 Q6 9 3.5 6Z" fill="currentColor" opacity="0.6" />
            </svg>
            <span class="item-text">{{ truncate(item.question || "分析任务", 22) }}</span>
          </button>
        </div>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-label">过去 7 天</div>
        <div v-if="!historyLoading && pastWeekHistory.length === 0" class="sidebar-empty-hint">
          暂无记录
        </div>
        <div v-else class="sidebar-list">
          <button
            v-for="item in pastWeekHistory"
            :key="item.task_id"
            class="sidebar-item"
            @click="loadHistoryTask(item)"
          >
            <svg class="item-icon" width="12" height="12" viewBox="0 0 12 12" fill="none">
              <circle cx="6" cy="6" r="5.5" stroke="currentColor" stroke-width="1" />
              <path d="M3.5 6 Q6 3 8.5 6 Q6 9 3.5 6Z" fill="currentColor" opacity="0.6" />
            </svg>
            <span class="item-text">{{ truncate(item.question || "分析任务", 22) }}</span>
          </button>
        </div>
      </div>

      <!-- Quick categories -->
      <div class="sidebar-section sidebar-categories">
        <div class="sidebar-section-label">快速分类</div>
        <div class="category-list">
          <button
            v-for="cat in categories"
            :key="cat.key"
            class="category-link"
            @click="handleCategoryClick(cat.placeholder)"
          >
            <span class="cat-dot" :style="{ background: cat.color }" />
            {{ cat.name }}
          </button>
        </div>
      </div>

      <!-- Bottom status -->
      <div class="sidebar-footer">
        <div class="status-dot" />
        <span>系统正常</span>
      </div>
    </aside>

    <!-- ════════════════════════════════════════════════════ -->
    <!-- MAIN: Warm parchment — editorial reading experience -->
    <!-- ════════════════════════════════════════════════════ -->
    <main class="main">
      <div ref="scrollAreaRef" class="scroll-area">
        <!-- Welcome state (no messages yet) -->
        <WelcomeSection
          v-if="messages.length === 0 && !reportContent"
          :greeting-text="greetingText"
          :quick-questions="quickQuestions"
          @select="handleWelcomeSelect"
        />

        <!-- Active chat area -->
        <div v-else class="reasoning">
          <!-- Error state -->
          <div v-if="error" class="error-card">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5" />
              <path
                d="M8 5v3M8 10.5v.5"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
              />
            </svg>
            <span>{{ error }}</span>
            <button class="btn-retry" @click="handleRetry">重试</button>
          </div>

          <!-- HITL Clarification Panel -->
          <div v-if="isWaitingForClarification && pendingClarification" class="clarification-panel">
            <div class="clarification-header">
              <span class="clarification-icon">💬</span>
              <span class="clarification-label">需要澄清</span>
            </div>
            <div class="clarification-question">{{ pendingClarification.question }}</div>

            <!-- Option buttons (approach_choice / with options) -->
            <div v-if="pendingClarification.options?.length" class="clarification-options">
              <button
                v-for="(opt, idx) in pendingClarification.options"
                :key="idx"
                class="clarification-option-btn"
                @click="resolveClarification(opt.label)"
              >
                {{ opt.label }}
                <span v-if="opt.description" class="option-desc">{{ opt.description }}</span>
              </button>
            </div>

            <!-- Text input (missing_info / ambiguous) -->
            <div v-else class="clarification-input-area">
              <input
                v-model="clarificationAnswer"
                class="clarification-input"
                placeholder="输入回答..."
                @keyup.enter="resolveClarification(clarificationAnswer)"
              />
              <button
                class="clarification-send-btn"
                :disabled="!clarificationAnswer.trim()"
                @click="resolveClarification(clarificationAnswer)"
              >
                发送
              </button>
            </div>
          </div>

          <!-- TDesign ChatList with custom slots -->
          <ChatList :data="tdesignItems" :is-stream-load="isLoading" layout="both" auto-scroll>
            <!-- #reasoning slot — 渲染 ThinkingPanel -->
            <template #reasoning="{ item }">
              <ThinkingPanel
                v-if="item.reasoning"
                :content="item.reasoning.content"
                :loading="isLoading"
                :collapsed="item.reasoning.collapsed"
              />
            </template>

            <!-- #content slot — 渲染 ToolCallStep + 消息内容 -->
            <template #content="{ item }">
              <template v-if="item.role === 'assistant'">
                <!-- 找到对应的原始 ChatMessageItem -->
                <template v-for="msg in messages" :key="msg.id">
                  <template v-if="msg.id === item.id">
                    <!-- Tool calls -->
                    <div v-if="msg.toolCalls && msg.toolCalls.length > 0" class="t-chat-tool-chain">
                      <ToolCallStep
                        v-for="(tc, idx) in msg.toolCalls"
                        :key="tc.id || idx"
                        :tool-call="tc"
                      />
                    </div>
                    <!-- Suggestions -->
                    <div
                      v-if="msg.suggestions && msg.suggestions.length > 0"
                      class="t-chat-suggestions"
                    >
                      <button
                        v-for="(s, idx) in msg.suggestions"
                        :key="idx"
                        class="suggestion-chip"
                        @click="handleSuggestionClick(s.content ?? s.text ?? '')"
                      >
                        {{ s.content ?? s.text ?? "" }}
                      </button>
                    </div>
                  </template>
                </template>
              </template>
            </template>

            <!-- #avatar slot — 自定义头像 -->
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
                <line x1="0" y1="6" x2="20" y2="6" stroke="#d0ccc6" stroke-width="1" />
                <circle cx="24" cy="6" r="3" fill="none" stroke="#c9943a" stroke-width="1" />
                <line x1="28" y1="6" x2="48" y2="6" stroke="#d0ccc6" stroke-width="1" />
              </svg>
            </div>
            <CustomMarkdownRenderer :content="reportContent" class="report-body" />
            <div class="compliance-stamp">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 1L13 4v5L7 13 1 9V4L7 1Z" stroke="currentColor" stroke-width="1.2" />
                <path
                  d="M7 5v2.5M7 9.5v.5"
                  stroke="currentColor"
                  stroke-width="1.2"
                  stroke-linecap="round"
                />
              </svg>
              本报告由清水投研系统 AI 生成，仅供投资研究参考，不构成任何投资建议
            </div>

            <!-- Message actions -->
            <div class="message-actions">
              <el-button size="small" text @click="handleCopyContent">
                <el-icon><CopyDocument /></el-icon>
                复制
              </el-button>
              <el-button size="small" text @click="handleGoodFeedback">
                <el-icon><Goods /></el-icon>
              </el-button>
              <el-button size="small" text @click="handleBadFeedback">
                <el-icon><CircleClose /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- ChatSender (TDesign t-chat input) -->
      <ChatSender
        v-model="inputText"
        :loading="isLoading"
        placeholder="输入您的问题，开启 AI 投研分析…"
        @send="handleSend"
        @stop="handleStop"
      />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from "vue";
import { getTaskResult } from "../api/agent.js";
import { useChatSession } from "@/composables/useChatSession";
import { useHistoryData } from "@/composables/useHistoryData";
import { ChatList, ChatSender } from "@tdesign-vue-next/chat";
import "@tdesign-vue-next/chat/es/style/index.css";
import { useTDesignAdapter } from "@/composables/useTDesignAdapter";
import WelcomeSection from "@/components/WelcomeSection.vue";
import CustomMarkdownRenderer from "@/components/CustomMarkdownRenderer.vue";
import ThinkingPanel from "@/components/ThinkingPanel.vue";
import ToolCallStep from "@/components/ToolCallStep.vue";
import { CopyDocument, Goods, CircleClose } from "@element-plus/icons-vue";
import { UserRound, Sparkles } from "lucide-vue-next";

// ─────────────────────────────────────────────────────────────────────────────
// Chat session (replaces manual SSE + message state)
// ─────────────────────────────────────────────────────────────────────────────
const {
  messages,
  threadId,
  taskId,
  isLoading,
  error,
  thinkingCollapsed,
  isConnected,
  sendMessage,
  stop,
  reset,
  startNewConversation,
  pendingClarification,
  isWaitingForClarification,
  clarificationAnswer,
  resolveClarification,
} = useChatSession();

// TDesign adapter — maps ChatMessageItem[] → t-chat items
// 注意：scheduleAutoCollapse 由 useTDesignAdapter 统一管理 expansion state
const { tdesignItems, expansionMap, toggleExpand, scheduleAutoCollapse } =
  useTDesignAdapter(messages);

// History data (extracted to composable)
const {
  loading: historyLoading,
  recent: recentHistory,
  pastWeek: pastWeekHistory,
  load: loadHistory,
  truncate,
} = useHistoryData();

// Input text state for ChatSender
const inputText = ref("");

// ─────────────────────────────────────────────────────────────────────────────
// Report state (separate from chat messages — report is a final artifact)
// ─────────────────────────────────────────────────────────────────────────────
const reportContent = ref("");

// Watch for task completion to fetch the final report
const lastTaskId = ref("");
const messagesLength = computed(() => messages.value.length);

// When loading stops and we have a taskId, fetch the report
// When loading stops and we have a taskId, fetch the final report
watch([isLoading, taskId], async ([loading, tid], [prevLoading]) => {
  if (prevLoading && !loading && tid && tid !== lastTaskId.value) {
    lastTaskId.value = tid;
    await fetchFinalReport(tid);
  }
});

async function fetchFinalReport(tid: string) {
  try {
    const res = await getTaskResult(tid);
    const raw = res.reportContent || res.content || "";
    if (raw) {
      reportContent.value = raw;
    }
  } catch {
    // Report fetch failed — content already streamed via ChatList
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// History & Categories
// ─────────────────────────────────────────────────────────────────────────────
const scrollAreaRef = ref<HTMLElement | null>(null);

const categories = [
  { key: "sector", name: "赛道分析", placeholder: "分析光模块赛道的竞争格局", color: "#3b6fd4" },
  { key: "stock", name: "个股深度", placeholder: "中际旭创的投资价值分析", color: "#c9943a" },
  { key: "compare", name: "板块对比", placeholder: "对比光伏和锂电行业的景气度", color: "#2d9e6c" },
  {
    key: "event",
    name: "事件驱动",
    placeholder: "美国芯片出口管制对国产替代的影响",
    color: "#d44d4d",
  },
];

const quickQuestions = ["AI算力链条还能投吗？", "光伏行业景气度如何？", "低空经济机会分析"];

const greetingText = computed(() => {
  const hour = new Date().getHours();
  if (hour < 6) return "凌晨好";
  if (hour < 12) return "上午好";
  if (hour < 18) return "下午好";
  return "晚上好";
});

// WelcomeSection handler
function handleWelcomeSelect(question: string) {
  handleSend(question);
}

// ─────────────────────────────────────────────────────────────────────────────
// Actions
// ─────────────────────────────────────────────────────────────────────────────

const lastQuestion = ref("");

async function handleSend(text: string) {
  lastQuestion.value = text;
  reportContent.value = "";
  lastTaskId.value = "";
  inputText.value = "";
  await sendMessage(text, scheduleAutoCollapse);
}

function handleStop() {
  inputText.value = "";
  stop();
}

function handleRetry(): void {
  const question = lastQuestion.value;
  if (question) {
    reset();
    sendMessage(question);
  }
}

function handleCategoryClick(placeholder: string) {
  handleSend(placeholder);
}

function handleSuggestionClick(value: string) {
  handleSend(value);
}

async function loadHistoryTask(item: any) {
  try {
    const res = await getTaskResult(item.task_id);
    const raw = res.reportContent || res.content || "";
    reportContent.value = raw;
  } catch {
    // Error already handled by useChatSession
  }
}

function handleCopyContent() {
  const content = reportContent.value;
  if (content) {
    navigator.clipboard.writeText(content).catch(() => {});
  }
}

function handleGoodFeedback() {
  // TODO: wire to feedback API
}

function handleBadFeedback() {
  // TODO: wire to feedback API
}

// ─────────────────────────────────────────────────────────────────────────────
// Lifecycle
// ─────────────────────────────────────────────────────────────────────────────
onMounted(loadHistory);
</script>

<style scoped>
/* ══════════════════════════════════════════════════════════ */
/* LAYOUT */
/* ══════════════════════════════════════════════════════════ */
.layout {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
}

/* ══════════════════════════════════════════════════════════ */
/* SIDEBAR — Ledger Spine with binding holes */
/* ══════════════════════════════════════════════════════════ */
.sidebar {
  width: 260px;
  flex-shrink: 0;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-sidebar);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-image:
    radial-gradient(ellipse at 0% 0%, rgba(201, 148, 58, 0.05) 0%, transparent 55%),
    radial-gradient(ellipse at 100% 100%, rgba(59, 111, 212, 0.03) 0%, transparent 55%);
  /* Ledger Spine — 书脊深墨色 */
  background-color: var(--ledger-spine);
  position: relative;
}

/* ── Ledger Spine Binding Holes ────────────────────── */
.sidebar::before {
  content: "";
  position: absolute;
  left: 12px;
  top: 80px;
  bottom: 80px;
  width: 8px;
  background-image: radial-gradient(circle at 50% 50%, var(--ledger-spine) 5px, transparent 6px);
  background-size: 8px 40px;
  background-repeat: repeat-y;
  background-position: 0 0;
  opacity: 0.6;
  animation: fade-in 0.6s ease both;
  pointer-events: none;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 22px 20px 18px;
  border-bottom: 1px solid var(--border-sidebar);
  animation: fade-in 0.4s ease both;
}
.logo-mark {
  flex-shrink: 0;
}
.logo-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.logo-name {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  color: var(--text-sidebar-hi);
  letter-spacing: 0.5px;
  line-height: 1.2;
}
.logo-sub {
  font-family: var(--font-ui);
  font-size: 10px;
  color: var(--text-sidebar-muted);
  letter-spacing: 1px;
  text-transform: uppercase;
}

.btn-new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin: 14px 16px;
  padding: 9px 16px;
  border-radius: 8px;
  border: 1px solid rgba(184, 134, 11, 0.35);
  background: var(--accent-gold-dim);
  color: var(--ledger-gold);
  font-family: var(--font-ui);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  animation: fade-in 0.4s 0.1s ease both;
}
.btn-new-chat:hover {
  background: rgba(232, 163, 23, 0.2);
  border-color: rgba(232, 163, 23, 0.6);
  transform: translateY(-1px);
}

.sidebar-section {
  padding: 16px 16px 8px;
  animation: fade-in 0.4s ease both;
}
.sidebar-section:nth-child(3) {
  animation-delay: 0.15s;
}
.sidebar-section:nth-child(4) {
  animation-delay: 0.2s;
}

.sidebar-section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--text-sidebar-muted);
  margin-bottom: 8px;
  padding: 0 4px;
}

.sidebar-loading {
  padding: 8px 4px;
}
.loading-dots {
  display: flex;
  gap: 5px;
  align-items: center;
}
.loading-dots span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--text-sidebar-muted);
  animation: fade-in 0.6s ease infinite alternate;
}
.loading-dots span:nth-child(2) {
  animation-delay: 0.2s;
}
.loading-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

.sidebar-empty-hint {
  font-size: 11px;
  color: var(--text-sidebar-muted);
  padding: 6px 4px;
}

.sidebar-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 8px;
  border-radius: 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
  color: var(--text-sidebar);
  border-bottom: 1px solid rgba(184, 134, 11, 0.06);
}
.sidebar-item:last-child {
  border-bottom: none;
}
.sidebar-item:hover {
  background: var(--ledger-spine-3);
  color: var(--text-sidebar-hi);
}
.item-icon {
  flex-shrink: 0;
  color: var(--text-sidebar-muted);
}
.item-text {
  font-size: 12px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

/* Quick categories — 快速分类 */
.sidebar-categories {
  margin-top: auto;
}
.category-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.category-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-sidebar);
  transition:
    background 0.15s,
    color 0.15s;
  text-align: left;
  border-radius: 4px;
}
.category-link:hover {
  background: var(--ledger-spine-3);
  color: var(--text-sidebar-hi);
}
.cat-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* Sidebar footer */
.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 12px 20px;
  border-top: 1px solid var(--border-sidebar);
  font-size: 11px;
  color: var(--text-sidebar-muted);
  animation: fade-in 0.4s 0.3s ease both;
}
.status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--status-success);
  animation: fade-in 2s ease infinite;
}

/* ══════════════════════════════════════════════════════════ */
/* MAIN — warm parchment */
/* ══════════════════════════════════════════════════════════ */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-main);
  overflow: hidden;
}

.scroll-area {
  flex: 1;
  overflow-y: auto;
  padding-bottom: 100px;
}

/* ── Reasoning / active area ───────────────────────────── */
.reasoning {
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
  padding: 36px 40px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  animation: fade-in 0.35s ease both;
}

/* Report section — 账页卡片 */
.report-section {
  background: var(--ledger-entry);
  border: 1px solid var(--ledger-rule);
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  padding: 32px 40px;
  margin-top: 24px;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.report-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 8px 0 24px;
  opacity: 0.8;
  animation: fade-in 0.4s ease both;
}
/* report-body styles moved to App.vue — Home.vue specific overrides */
:deep(.report-body) {
  font-size: 14.5px;
  line-height: 1.9;
}
:deep(.report-body code) {
  color: var(--ledger-gold);
  border: 1px solid var(--ledger-rule);
}

/* Compliance Stamp — 合规印章 */
.compliance-stamp {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 32px;
  padding: 16px 20px;
  background: var(--ledger-entry);
  border: 2px solid var(--ledger-gold);
  border-radius: 4px;
  font-size: 11px;
  color: var(--ledger-gold);
  line-height: 1.6;
  text-align: center;
  animation: fade-in 0.4s 0.1s ease both;
  position: relative;
  font-weight: 500;
  letter-spacing: 0.5px;
}
.compliance-stamp::before {
  content: "";
  position: absolute;
  inset: 4px;
  border: 1px solid rgba(184, 134, 11, 0.3);
  border-radius: 2px;
  pointer-events: none;
}
.compliance-stamp svg {
  color: var(--ledger-gold);
  flex-shrink: 0;
}

.message-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding-left: 0;
}

/* ── Error — ledger red styling ────────────────────── */
.error-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: var(--ledger-entry);
  border: 1px solid var(--ledger-red);
  border-radius: 4px;
  color: var(--ledger-red);
  font-size: 13px;
  animation: fade-in 0.3s ease both;
}
.error-card svg {
  flex-shrink: 0;
}
.error-card span {
  flex: 1;
}
.btn-retry {
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid var(--status-error);
  background: transparent;
  color: var(--status-error);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
.btn-retry:hover {
  background: var(--status-error);
  color: #fff;
}

/* ══════════════════════════════════════════════════════════ */
/* ANIMATIONS —克制版 */
/* ══════════════════════════════════════════════════════════ */
@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

/* ══════════════════════════════════════════════════════════ */
/* T-CHAT SLOT STYLES (avatar styles moved to App.vue) */
/* ══════════════════════════════════════════════════════════ */
.t-chat-tool-chain {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}
.t-chat-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.suggestion-chip {
  font-size: 12px;
  padding: 5px 13px;
  border-radius: 14px;
  border: 1px solid var(--border-light);
  background: var(--bg-main-card);
  color: var(--text-main-2);
  cursor: pointer;
  transition: all 0.18s ease;
}
.suggestion-chip:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
  background: rgba(59, 111, 212, 0.06);
  transform: translateY(-1px);
  box-shadow: 0 2px 6px -2px rgba(59, 111, 212, 0.18);
}

.clarification-panel {
  margin: 16px 12px;
  padding: 16px;
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  border-radius: 8px;
}
.clarification-header {
  font-size: 13px;
  color: #1d7c8a;
  margin-bottom: 8px;
}
.clarification-question {
  font-size: 15px;
  font-weight: 500;
  margin-bottom: 12px;
}
.clarification-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.clarification-option-btn {
  padding: 8px 16px;
  background: white;
  border: 1px solid #d6e4ff;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
}
.clarification-option-btn:hover {
  background: #e6f0ff;
  border-color: #1d7c8a;
}
.option-desc {
  display: block;
  font-size: 12px;
  color: #666;
  margin-top: 2px;
}
.clarification-input-area {
  display: flex;
  gap: 8px;
}
.clarification-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
}
.clarification-send-btn {
  padding: 8px 20px;
  background: #1d7c8a;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.clarification-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
