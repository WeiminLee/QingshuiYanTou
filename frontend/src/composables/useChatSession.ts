import { ref, shallowRef, onUnmounted } from "vue";
import { streamReport, resolveClarification as apiResolve } from "@/api/agent.js";
import type { ChatMessageItem, ToolCallItem, SuggestionItem, ClarificationItem } from "@/types/chat";
import { useStreamPipeline } from "./useStreamPipeline";
import { useStreamParser } from "./useStreamParser";

function generateId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function generateUUID(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function extractPayload(raw: string): Record<string, any> {
  const parsed = JSON.parse(raw);
  if (parsed && typeof parsed === "object" && parsed.data && typeof parsed.data === "object") {
    return { ...parsed.data, _seq: parsed.seq, _turn: parsed.turn, _type: parsed.type };
  }
  return parsed ?? {};
}

export function useChatSession() {
  const messages = ref<ChatMessageItem[]>([]);
  const threadId = ref<string>("");
  const taskId = ref<string>("");
  const isLoading = ref(false);
  const error = ref<string | null>(null);
  const thinkingCollapsed = ref(false);
  const isConnected = ref(false);
  const pendingClarification = ref<ClarificationItem | null>(null);
  const isWaitingForClarification = ref(false);
  const clarificationAnswer = ref("");

  const eventSource = shallowRef<EventSource | null>(null);
  const currentAssistantId = ref<string | null>(null);
  let collapseTimer: ReturnType<typeof setTimeout> | null = null;

  // useStreamParser: JSON/XML/regex-json/plain-text parsing
  const streamParser = useStreamParser();

  function findMessage(id: string): ChatMessageItem | undefined {
    return messages.value.find((m) => m.id === id);
  }

  function updateMessage(id: string, updates: Partial<ChatMessageItem>): void {
    const idx = messages.value.findIndex((m) => m.id === id);
    if (idx !== -1) {
      messages.value = messages.value.map((m) => (m.id === id ? { ...m, ...updates } : m));
    }
  }

  function addUserMessage(content: string): string {
    const id = generateId("user");
    messages.value = [...messages.value, { id, role: "user", content, timestamp: Date.now() }];
    return id;
  }

  function addAssistantMessage(): string {
    const id = generateId("assistant");
    messages.value = [
      ...messages.value,
      {
        id,
        role: "assistant",
        content: "",
        timestamp: Date.now(),
        thinking: true,
        thinkingContent: "",
        thinkingLoading: true,
        suggestions: [],
        toolCalls: [],
      },
    ];
    currentAssistantId.value = id;
    return id;
  }

  function appendThinking(delta: string): void {
    const id = currentAssistantId.value;
    if (!id) return;
    const msg = findMessage(id);
    if (!msg) return;
    updateMessage(id, { thinkingContent: (msg.thinkingContent || "") + delta });
  }

  function appendContent(delta: string): void {
    const id = currentAssistantId.value;
    if (!id) return;
    const msg = findMessage(id);
    if (!msg) return;
    updateMessage(id, { content: msg.content + delta, thinkingLoading: false });
  }

  function addToolCall(toolCall: ToolCallItem): void {
    const id = currentAssistantId.value;
    if (!id) return;
    const msg = findMessage(id);
    if (!msg) return;
    updateMessage(id, { toolCalls: [...(msg.toolCalls || []), toolCall] });
  }

  function updateToolCallById(id: string, updates: Partial<ToolCallItem>): void {
    const msgId = currentAssistantId.value;
    if (!msgId) return;
    const msg = findMessage(msgId);
    if (!msg || !msg.toolCalls) return;
    const toolCalls = msg.toolCalls.map((tc) => (tc.id === id ? { ...tc, ...updates } : tc));
    updateMessage(msgId, { toolCalls });
  }

  function hasToolCallId(id: string): boolean {
    const msgId = currentAssistantId.value;
    if (!msgId) return false;
    const msg = findMessage(msgId);
    return !!msg?.toolCalls?.some((tc) => tc.id === id);
  }

  function setSuggestions(suggestions: SuggestionItem[]): void {
    const id = currentAssistantId.value;
    if (!id) return;
    updateMessage(id, { suggestions });
  }

  function finishCurrentMessage(): void {
    const id = currentAssistantId.value;
    if (!id) return;
    updateMessage(id, { thinkingLoading: false, thinking: false });
  }

  function connectSSE(
    tid: string,
    scheduleAutoCollapse: ((msgId: string, delayMs?: number) => void) | undefined,
  ): void {
    if (eventSource.value) {
      eventSource.value.close();
    }

    const apiKey = import.meta.env.VITE_API_KEY;
    const query = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : "";
    const url = `/api/v1/agent/stream/${tid}${query}`;
    const es = new EventSource(url);
    eventSource.value = es;
    isConnected.value = true;

    // 创建 pipeline，传入当前 assistant message ID
    const pipeline = useStreamPipeline(
      {
        onReasonDelta: appendThinking,
        onReasonComplete: (msgId, _durationMs) => {
          // 推理完成，调度延迟折叠（由 useTDesignAdapter 统一管理状态）
          scheduleAutoCollapse?.(msgId, 1000);
        },
        onContent: (_msgId, content) => {
          appendContent(content);
        },
        onToolStart: (_msgId, toolCall) => {
          if (!hasToolCallId(toolCall.id)) {
            addToolCall(toolCall);
          }
        },
        onToolEnd: (_msgId, toolId, result, durationMs, preview) => {
          // 使用 streamParser 解析工具结果
          const parseResult = streamParser.autoDetectParse(result);
          updateToolCallById(toolId, {
            result,
            status: "done",
            duration_ms: durationMs,
            preview,
            parsedResult: parseResult.success ? parseResult.data : null,
          });
        },
        onComplete: (_msgId) => {
          isLoading.value = false;
          finishCurrentMessage();
          scheduleThinkingCollapse();
          isConnected.value = false;
          es.close();
        },
        onError: (_msgId, errMsg) => {
          error.value = errMsg;
          isLoading.value = false;
          finishCurrentMessage();
          isConnected.value = false;
          es.close();
        },
      },
      currentAssistantId,
    );

    es.onopen = () => {
      isConnected.value = true;
    };

    es.onerror = () => {
      isConnected.value = false;
      isLoading.value = false;
      es.close();
    };

    es.addEventListener("reasoning_start", (e: MessageEvent) => {
      try {
        const data = extractPayload(e.data);
        pipeline.pushEvent("reasoning_start", { ...data, _messageId: currentAssistantId.value });
      } catch {
        // Ignore parse errors
      }
    });

    // thinking 事件 -> pipeline.pushEvent
    es.addEventListener("thinking", (e: MessageEvent) => {
      try {
        const data = extractPayload(e.data);
        pipeline.pushEvent("thinking", { ...data, _messageId: currentAssistantId.value });
      } catch {
        // Ignore parse errors
      }
    });

    // tool_called 事件
    es.addEventListener("tool_called", (e: MessageEvent) => {
      try {
        const data = extractPayload(e.data);
        pipeline.pushEvent("tool_called", { ...data, _messageId: currentAssistantId.value });
      } catch {
        // Ignore parse errors
      }
    });

    // tool_result 事件
    es.addEventListener("tool_result", (e: MessageEvent) => {
      try {
        const data = extractPayload(e.data);
        pipeline.pushEvent("tool_result", { ...data, _messageId: currentAssistantId.value });
      } catch {
        // Ignore parse errors
      }
    });

    for (const eventName of ["task_started", "task_running", "task_completed", "task_failed"]) {
      es.addEventListener(eventName, (e: MessageEvent) => {
        try {
          const data = extractPayload(e.data);
          pipeline.pushEvent(eventName, { ...data, _messageId: currentAssistantId.value });
        } catch {
          // Ignore parse errors
        }
      });
    }

    // stream_end 事件
    es.addEventListener("stream_end", (e: MessageEvent) => {
      try {
        const data = extractPayload(e.data);
        pipeline.pushEvent("stream_end", { ...data, _messageId: currentAssistantId.value });
      } catch {
        isLoading.value = false;
        finishCurrentMessage();
        scheduleThinkingCollapse();
        isConnected.value = false;
        es.close();
      }
    });

    // error 事件
    es.addEventListener("error", (e: MessageEvent) => {
      try {
        const data = extractPayload(e.data);
        pipeline.pushEvent("error", { ...data, _messageId: currentAssistantId.value });
      } catch {
        error.value = "连接错误";
        isLoading.value = false;
        finishCurrentMessage();
        isConnected.value = false;
        es.close();
      }
    });

    es.addEventListener("clarification_request", (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data);
        const data = parsed.data || parsed;
        pendingClarification.value = {
          clarification_id: data.clarification_id || "",
          question: data.question || "",
          type: data.type || "ambiguous",
          options: data.options,
          context: data.context,
        };
        isWaitingForClarification.value = true;
        isLoading.value = false;
      } catch (err) {
        console.error("[HITL] Failed to parse clarification_request:", err);
      }
    });

    es.addEventListener("clarification_resolved", () => {
      isWaitingForClarification.value = true;
    });
  }

  function scheduleThinkingCollapse(): void {
    if (collapseTimer) clearTimeout(collapseTimer);
    collapseTimer = setTimeout(() => {
      thinkingCollapsed.value = true;
    }, 1000);
  }

  async function sendMessage(
    question: string,
    scheduleAutoCollapse?: (msgId: string, delayMs?: number) => void,
  ): Promise<void> {
    if (!question.trim() || isLoading.value) return;

    error.value = null;
    thinkingCollapsed.value = false;

    if (!threadId.value) {
      threadId.value = generateUUID();
    }

    addUserMessage(question.trim());
    addAssistantMessage();
    isLoading.value = true;

    try {
      const res = await streamReport({
        question: question.trim(),
        thread_id: threadId.value,
        max_turns: 4,
      });

      taskId.value = res.task_id;
      connectSSE(res.task_id, scheduleAutoCollapse);
    } catch (err: any) {
      error.value = err?.message || "Failed to start analysis";
      isLoading.value = false;
      finishCurrentMessage();
    }
  }

  async function resolveClarification(answer: string) {
    if (!taskId.value || !pendingClarification.value) return;
    try {
      await apiResolve(taskId.value, {
        answer,
        clarification_id: pendingClarification.value.clarification_id,
      });
      pendingClarification.value = null;
      isWaitingForClarification.value = true;
    } catch (err) {
      console.error("[HITL] resolveClarification failed:", err);
    }
  }

  function stop(): void {
    if (eventSource.value) {
      eventSource.value.close();
      eventSource.value = null;
    }
    isConnected.value = false;
    isLoading.value = false;
    finishCurrentMessage();
  }

  function reset(): void {
    stop();
    messages.value = [];
    threadId.value = "";
    taskId.value = "";
    error.value = null;
    thinkingCollapsed.value = false;
    currentAssistantId.value = null;
  }

  function startNewConversation(): void {
    reset();
  }

  onUnmounted(() => {
    if (eventSource.value) {
      eventSource.value.close();
    }
    if (collapseTimer) {
      clearTimeout(collapseTimer);
    }
  });

  return {
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
  };
}
