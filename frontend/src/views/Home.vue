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
        新建任务
      </button>

      <SignalRadar @ask-signal="handleAskSignal" />

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
            <span class="item-text">{{ truncate(item.question || "", 22) }}</span>
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
            <span class="item-text">{{ truncate(item.question || "", 22) }}</span>
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

          <!-- 自定义消息列表（open-webui 风：用户右、AI 左，绕开 TDesign slot 机制）-->
          <div class="msg-list">
            <div
              v-for="msg in messages"
              :key="msg.id"
              class="msg-row"
              :class="`msg-row--${msg.role}`"
            >
              <!-- 用户消息：右侧灰气泡 -->
              <div v-if="msg.role === 'user'" class="msg-bubble-user">
                {{ msg.content }}
              </div>

              <!-- AI 消息：左侧通栏 -->
              <div v-else class="msg-assistant">
                <div class="msg-avatar-ai">
                  <Sparkles :size="15" :stroke-width="1.8" />
                </div>
                <div class="msg-assistant-body">
                  <!-- Tool calls -->
                  <div v-if="msg.toolCalls && msg.toolCalls.length > 0" class="t-chat-tool-chain">
                    <ToolCallStep
                      v-for="(tc, idx) in msg.toolCalls"
                      :key="tc.id || idx"
                      :tool-call="tc"
                    />
                  </div>
                  <!-- 流式答案：气泡内 markdown -->
                  <CustomMarkdownRenderer
                    v-if="msg.content"
                    :content="msg.content"
                    class="report-body assistant-answer"
                  />
                  <!-- 流式加载光标（尚无内容时）-->
                  <span v-else-if="isLoading" class="stream-cursor" />
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
                </div>
              </div>
            </div>
          </div>

          <!-- Final report -->
          <!-- 可信推理链（仅真分析显示；答案本体已在上方气泡流式渲染，不再重复）-->
          <div v-if="reportContent && !isCasualChat" class="report-section">
            <div class="report-divider">
              <svg width="48" height="12" viewBox="0 0 48 12">
                <line x1="0" y1="6" x2="20" y2="6" stroke="#d0ccc6" stroke-width="1" />
                <circle cx="24" cy="6" r="3" fill="none" stroke="#c9943a" stroke-width="1" />
                <line x1="28" y1="6" x2="48" y2="6" stroke="#d0ccc6" stroke-width="1" />
              </svg>
            </div>
            <CredibleReasoningPanel
              :tool-calls="latestAssistantToolCalls"
              :report-json="reportJson"
              :reasoning-text="latestAssistantReasoning"
              :is-loading="isLoading"
            />
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
              <el-button
                size="small"
                text
                :type="submittedFeedback === 'good' ? 'primary' : ''"
                @click="handleGoodFeedback"
              >
                <el-icon><Goods /></el-icon>
              </el-button>
              <el-button
                size="small"
                text
                :type="submittedFeedback === 'bad' ? 'danger' : ''"
                @click="handleBadFeedback"
              >
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
import { ref, computed, watch, onMounted, nextTick } from "vue";
import { getTaskResult, submitAgentFeedback } from "../api/agent.js";
import { useChatSession } from "@/composables/useChatSession";
import { useHistoryData } from "@/composables/useHistoryData";
import { ChatList, ChatSender } from "@tdesign-vue-next/chat";
import "@tdesign-vue-next/chat/es/style/index.css";
import { useTDesignAdapter } from "@/composables/useTDesignAdapter";
import WelcomeSection from "@/components/WelcomeSection.vue";
import CustomMarkdownRenderer from "@/components/CustomMarkdownRenderer.vue";
import CredibleReasoningPanel from "@/components/CredibleReasoningPanel.vue";
import ThinkingPanel from "@/components/ThinkingPanel.vue";
import ToolCallStep from "@/components/ToolCallStep.vue";
import SignalRadar from "@/components/SignalRadar.vue";
import { CopyDocument, Goods, CircleClose } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { UserRound } from "lucide-vue-next";

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
const reportJson = ref<Record<string, any> | null>(null);
// 闲聊/非投研分析判定：无工具调用且无股票标的 → 视为普通对话，不套报告 chrome
const isCasualChat = computed(() => {
  const j = reportJson.value;
  if (!j) return false;
  const toolCount = j?.trace_summary?.tool_call_count ?? 0;
  const hasStock = !!(j?.ts_code && String(j.ts_code).trim());
  return toolCount === 0 && !hasStock;
});
// 报告级反馈：记录当前报告已提交的评价（"good"/"bad"/""），用于防重复与高亮
const submittedFeedback = ref("");
const latestAssistantToolCalls = computed(() => {
  const assistantMessages = messages.value.filter((m) => m.role === "assistant");
  const last = assistantMessages[assistantMessages.length - 1];
  return last?.toolCalls || [];
});
const latestAssistantReasoning = computed(() => {
  const assistantMessages = messages.value.filter((m) => m.role === "assistant");
  const last = assistantMessages[assistantMessages.length - 1];
  return last?.thinkingContent || "";
});

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
    reportJson.value = res.reportJson || null;
    if (raw) {
      reportContent.value = raw;
      submittedFeedback.value = ""; // 新报告，重置反馈状态
    }
  } catch {
    // Report fetch failed — content already streamed via ChatList
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// History & Categories
// ─────────────────────────────────────────────────────────────────────────────
const scrollAreaRef = ref<HTMLElement | null>(null);

// 自动滚动到底部（替代 TDesign ChatList 的 auto-scroll）
function scrollToBottom(): void {
  const el = scrollAreaRef.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}
// 消息内容变化（新消息 / 流式增量 / 报告）时滚到底
watch(
  [messages, reportContent],
  () => {
    nextTick(scrollToBottom);
  },
  { deep: true },
);

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

async function handleSend(text: string, options?: { signalId?: string }) {
  lastQuestion.value = text;
  reportContent.value = "";
  reportJson.value = null;
  lastTaskId.value = "";
  inputText.value = "";
  await sendMessage(text, scheduleAutoCollapse, options);
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

function handleAskSignal(payload: { signalId: string; question: string }) {
  handleSend(payload.question, { signalId: payload.signalId });
}

async function loadHistoryTask(item: any) {
  try {
    const res = await getTaskResult(item.task_id);
    const raw = res.reportContent || res.content || "";
    reportJson.value = res.reportJson || null;
    reportContent.value = raw;
    submittedFeedback.value = ""; // 切换报告，重置反馈状态
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

async function sendFeedback(rating: "good" | "bad") {
  const tid = taskId.value;
  if (!tid) {
    ElMessage.warning("暂无可反馈的报告");
    return;
  }
  if (submittedFeedback.value === rating) return; // 防重复
  try {
    await submitAgentFeedback({
      taskId: tid,
      rating,
      question: lastQuestion.value || undefined,
    });
    submittedFeedback.value = rating;
    ElMessage.success(rating === "good" ? "感谢反馈" : "已记录，我们会持续改进");
  } catch {
    ElMessage.error("反馈提交失败，请稍后重试");
  }
}

function handleGoodFeedback() {
  sendFeedback("good");
}

function handleBadFeedback() {
  sendFeedback("bad");
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
/* SIDEBAR — light companion surface aligned with the chat canvas */
/* ══════════════════════════════════════════════════════════ */
.sidebar {
  width: 280px;
  flex-shrink: 0;
  background: linear-gradient(180deg, var(--ow-bg) 0%, #fbfbfc 100%);
  border-right: 1px solid var(--ow-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-family: var(--ow-font);
  position: relative;
}

/* Soft inner rail keeps the sidebar distinct without returning to the old dark spine. */
.sidebar::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: linear-gradient(180deg, rgba(184, 134, 11, 0.18), rgba(14, 165, 233, 0.08));
  opacity: 0.75;
  pointer-events: none;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px 16px 22px;
  border-bottom: 1px solid var(--ow-border);
  animation: fade-in 0.4s ease both;
}
.logo-mark {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--ow-border);
  border-radius: 10px;
  background: var(--ow-surface);
}
.logo-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.logo-name {
  font-family: var(--ow-font);
  font-size: 15px;
  font-weight: 600;
  color: var(--ow-text);
  letter-spacing: 0;
  line-height: 1.2;
}
.logo-sub {
  font-family: var(--ow-font);
  font-size: 12px;
  color: var(--ow-text-2);
  letter-spacing: 0;
  text-transform: uppercase;
}

.btn-new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  align-self: stretch;
  min-height: 34px;
  margin: 12px 18px 12px;
  padding: 7px 12px;
  border-radius: var(--ow-radius-xs);
  border: 1px solid var(--ow-border-strong);
  background: var(--ow-bg);
  color: var(--ow-text);
  font-family: var(--ow-font);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  transition:
    background 0.15s,
    border-color 0.15s,
    box-shadow 0.15s,
    transform 0.15s;
  animation: fade-in 0.4s 0.1s ease both;
}
.btn-new-chat:hover {
  background: var(--ow-surface);
  border-color: #d8dbe0;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.sidebar-section {
  padding: 14px 18px 8px;
  animation: fade-in 0.4s ease both;
}
.sidebar-section:nth-child(3) {
  animation-delay: 0.15s;
}
.sidebar-section:nth-child(4) {
  animation-delay: 0.2s;
}

.sidebar-section-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0;
  color: var(--ow-text-2);
  margin-bottom: 8px;
  padding: 0 2px;
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
  background: var(--ow-text-3);
  animation: fade-in 0.6s ease infinite alternate;
}
.loading-dots span:nth-child(2) {
  animation-delay: 0.2s;
}
.loading-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

.sidebar-empty-hint {
  font-size: 13.5px;
  color: var(--ow-text-3);
  padding: 7px 2px;
}

.sidebar-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  min-height: 38px;
  padding: 8px 10px;
  border-radius: var(--ow-radius-xs);
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
  color: var(--ow-text-2);
}
.sidebar-item:last-child {
  border-bottom: none;
}
.sidebar-item:hover {
  background: var(--ow-surface);
  border-color: var(--ow-border);
  color: var(--ow-text);
}
.item-icon {
  flex-shrink: 0;
  color: var(--ow-text-3);
}
.item-text {
  font-size: 14px;
  line-height: 1.45;
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
  gap: 5px;
}
.category-link {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 8px 10px;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  font-family: var(--ow-font);
  font-size: 14px;
  color: var(--ow-text-2);
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
  text-align: left;
  border-radius: var(--ow-radius-xs);
}
.category-link:hover {
  background: var(--ow-surface);
  border-color: var(--ow-border);
  color: var(--ow-text);
}
.cat-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* Sidebar footer */
.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 13px 20px 15px;
  border-top: 1px solid var(--ow-border);
  font-size: 13.5px;
  color: var(--ow-text-2);
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
  /* open-webui 对话区：干净白底 + Inter/系统 sans 字体 */
  background: var(--ow-bg);
  color: var(--ow-text);
  font-family: var(--ow-font);
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

/* Report section — open-webui 干净卡片 */
.report-section {
  background: var(--ow-bg);
  border: 1px solid var(--ow-border);
  border-radius: var(--ow-radius-md);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  padding: 28px 32px;
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 0;
}
/* 闲聊/普通对话：去掉卡片外壳，像普通消息一样通栏呈现 */
.report-section--plain {
  border: none;
  box-shadow: none;
  padding: 4px 0 0;
  margin-top: 4px;
}
.report-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 8px 0 24px;
  opacity: 0.8;
  animation: fade-in 0.4s ease both;
}
/* report-body prose — open-webui 风 */
:deep(.report-body) {
  font-size: 15px;
  line-height: 1.75;
  color: var(--ow-text);
  font-family: var(--ow-font);
}
:deep(.report-body code) {
  color: var(--ow-text);
  background: var(--ow-code-bg);
  border: 1px solid var(--ow-border);
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

/* AI 答案：气泡内 markdown，通栏 prose（open-webui 风）*/
.assistant-answer {
  font-size: 15px;
  line-height: 1.75;
  color: var(--ow-text);
}

/* ── 自定义消息列表（open-webui 风）───────────────────────── */
.msg-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.msg-row {
  display: flex;
  width: 100%;
}
.msg-row--user {
  justify-content: flex-end;
}
.msg-row--assistant {
  justify-content: flex-start;
}

/* 用户气泡：右侧浅灰 */
.msg-bubble-user {
  background: var(--ow-surface);
  border-radius: var(--ow-radius-lg);
  padding: 10px 16px;
  font-size: 15px;
  line-height: 1.6;
  color: var(--ow-text);
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 80%;
}

/* AI 消息：左侧头像 + 通栏内容 */
.msg-assistant {
  display: flex;
  gap: 12px;
  width: 100%;
}
.msg-avatar-ai {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--ow-surface);
  border: 1px solid var(--ow-border);
  color: var(--ow-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.msg-assistant-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 用户消息：右侧浅灰气泡 */
.user-message-text {
  display: inline-block;
  background: var(--ow-surface);
  border-radius: var(--ow-radius-lg);
  padding: 10px 16px;
  font-size: 15px;
  line-height: 1.6;
  color: var(--ow-text);
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 100%;
}
/* 用户消息容器右对齐（TDesign .user 行是 row-reverse，内容靠右）*/
.reasoning :deep(.t-chat__inner.user .t-chat__content),
.reasoning :deep(.t-chat__inner.user .t-chat__detail) {
  align-items: flex-end;
  text-align: right;
}
.reasoning :deep(.t-chat__inner.user .t-chat__detail) {
  display: flex;
  flex-direction: column;
}

/* 流式加载光标 */
.stream-cursor {
  display: inline-block;
  width: 7px;
  height: 16px;
  background: var(--ow-text-3);
  border-radius: 1px;
  animation: cursor-blink 1s step-end infinite;
  vertical-align: text-bottom;
}
@keyframes cursor-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

/* ── open-webui 气泡覆盖 ─────────────────────────────────────
   用户消息：浅灰气泡 rounded-3xl 右对齐；AI 消息：通栏无气泡 */
.reasoning :deep(.t-chat__text--variant--base) {
  background: var(--ow-surface);
  border-radius: var(--ow-radius-lg);
  color: var(--ow-text);
  padding: 10px 16px;
}
.reasoning :deep(.t-chat__text--user) {
  color: var(--ow-text);
  font-size: 15px;
  line-height: 1.65;
}
/* AI 消息内容：去掉气泡背景，通栏 */
.reasoning :deep(.t-chat__text--variant--text),
.reasoning :deep(.t-chat__text--variant--outline) {
  background: transparent;
  border: none;
  padding: 0;
}
/* 角色名/时间：弱化为灰字 */
.reasoning :deep(.t-chat__name) {
  color: var(--ow-text-3);
  font-size: 12px;
  font-weight: 500;
}
/* 收窄头像与内容间距 */
.reasoning :deep(.t-chat__inner) {
  font-family: var(--ow-font);
}

.t-chat-tool-chain {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 8px;
}
.t-chat-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.suggestion-chip {
  font-size: 13px;
  padding: 6px 14px;
  border-radius: var(--ow-radius-sm);
  border: 1px solid var(--ow-border);
  background: transparent;
  color: var(--ow-text-2);
  cursor: pointer;
  transition: all 0.15s ease;
}
.suggestion-chip:hover {
  border-color: var(--ow-border-strong);
  color: var(--ow-text);
  background: var(--ow-hover);
}

/* ── open-webui 输入框：居中限宽 + 悬浮圆角 ───────────────── */
.main :deep(.t-chat-sender) {
  max-width: 800px;
  margin: 0 auto;
  padding: 0 20px 20px;
}
.main :deep(.t-chat-sender__textarea) {
  border-radius: var(--ow-radius-lg);
  border: 1px solid var(--ow-border-strong);
  box-shadow: 0 2px 14px rgba(0, 0, 0, 0.06);
  background: var(--ow-bg);
  font-family: var(--ow-font);
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.main :deep(.t-chat-sender__textarea--focus) {
  border-color: var(--ow-accent);
  box-shadow: 0 2px 18px rgba(14, 165, 233, 0.14);
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
