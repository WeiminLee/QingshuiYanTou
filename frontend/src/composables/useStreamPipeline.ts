/**
 * useStreamPipeline — SSE 事件管道 composable
 *
 * 合并自 persona StreamProcessor + ReasoningParser。
 * - StreamProcessor: SequenceReorderBuffer 缓冲 + 重排
 * - ReasoningParser: reasoning_start -> reason_delta -> reason_complete 状态机
 *
 * 清水后端事件映射:
 *   thinking     -> reason_delta（reasoning content 增量）
 *   stream_end  -> reason_complete（reasoning 结束）
 *   tool_called -> tool_start（工具开始）
 *   tool_result -> tool_end（工具结束）
 */

import { ref, onUnmounted, type Ref } from "vue";
import { SequenceReorderBuffer } from "@/utils/SequenceReorderBuffer";
import type { ToolCallItem, ClarificationItem, ClarificationOption } from "@/types/chat";

export interface ReasoningContext {
  startedAt: number | null;
  content: string;
  completedAt: number | null;
  durationMs: number | null;
  status: "pending" | "streaming" | "complete";
}

export interface StreamPipelineCallbacks {
  onReasonStart?: (messageId: string) => void;
  onReasonDelta?: (messageId: string, delta: string) => void;
  onReasonComplete?: (messageId: string, durationMs: number) => void;
  onToolStart?: (messageId: string, toolCall: ToolCallItem) => void;
  onToolEnd?: (
    messageId: string,
    toolId: string,
    result: string,
    durationMs: number,
    preview?: string,
  ) => void;
  onContent?: (messageId: string, content: string) => void;
  onComplete?: (messageId: string) => void;
  onError?: (messageId: string, error: string) => void;
  onClarification?: (item: ClarificationItem) => void;
}

export interface UseStreamPipelineReturn {
  /** 推送原始 SSE 事件到管道（由 useChatSession.connectSSE 调用） */
  pushEvent: (eventType: string, payload: unknown) => void;
  /** 手动完成当前推理（用于 stream_end） */
  completeReasoning: (messageId: string) => void;
  /** 重置管道状态 */
  reset: () => void;
}

export function useStreamPipeline(
  callbacks: StreamPipelineCallbacks,
  currentMessageId: Ref<string | null>,
): UseStreamPipelineReturn {
  // 推理上下文：messageId -> ReasoningContext
  const reasoningContexts = ref<Map<string, ReasoningContext>>(new Map());

  // SequenceReorderBuffer：事件重排
  const buffer = new SequenceReorderBuffer((payloadType: string, payload: unknown) => {
    handleBufferedEvent(payloadType, payload);
  });

  function handleBufferedEvent(payloadType: string, payload: unknown): void {
    const p = payload as Record<string, unknown>;
    const messageId: string = p?._messageId ?? currentMessageId.value ?? "";

    switch (payloadType) {
      case "thinking": {
        // thinking delta -> reason_delta
        const delta = p?.delta ?? "";
        if (!delta) return;
        // 确保 context 存在
        ensureReasoningContext(messageId);
        const ctx = reasoningContexts.value.get(messageId);
        if (ctx) {
          ctx.content += delta;
          ctx.status = "streaming";
        }
        callbacks.onReasonDelta?.(messageId, delta as string);
        break;
      }

      case "reasoning_start":
      case "reason_start": {
        // 显式 reasoning_start 事件（兼容旧 reason_start）
        ensureReasoningContext(messageId);
        callbacks.onReasonStart?.(messageId);
        break;
      }

      case "stream_end": {
        // stream_end -> reason_complete + content
        const content = p?.report_content ?? p?.content ?? "";
        if (content) {
          callbacks.onContent?.(messageId, content as string);
        }
        completeReasoningLogic(messageId);
        callbacks.onComplete?.(messageId);
        break;
      }

      case "tool_called": {
        // tool_called -> tool_start
        const toolId =
          (p?.id as string) || `tool-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
        const toolCall: ToolCallItem = {
          id: toolId,
          name: (p?.name as string) || "",
          status: "running",
          args: (p?.args as Record<string, unknown>) || {},
        };
        callbacks.onToolStart?.(messageId, toolCall);
        break;
      }

      case "tool_result": {
        // tool_result -> tool_end
        const toolId = (p?.id as string) || "";
        const result = (p?.result as string) || "";
        const durationMs = p?.duration_ms as number | undefined;
        const preview = p?.preview as string | undefined;
        callbacks.onToolEnd?.(messageId, toolId, result, durationMs ?? 0, preview);
        break;
      }

      case "task_started":
      case "task_running":
      case "task_completed":
      case "task_failed": {
        const toolId = (p?.task_id as string) || `task-${Date.now()}`;
        const status =
          payloadType === "task_failed"
            ? "error"
            : payloadType === "task_completed"
              ? "done"
              : "running";
        const result =
          (p?.result as string) || (p?.error as string) || (p?.status as string) || payloadType;
        if (payloadType === "task_started") {
          callbacks.onToolStart?.(messageId, {
            id: toolId,
            name: `task:${(p?.agent_name as string) || "subagent"}`,
            status,
            args: { title: p?.title },
          });
        } else {
          callbacks.onToolEnd?.(messageId, toolId, result, 0, result);
        }
        break;
      }

      case "error": {
        const errMsg = (p?.error as string) || "未知错误";
        callbacks.onError?.(messageId, errMsg);
        break;
      }

      case "clarification_request": {
        callbacks.onClarification?.({
          clarification_id: (p?.clarification_id as string) || "",
          question: (p?.question as string) || "",
          type: (p?.type as "missing_info" | "ambiguous" | "approach_choice" | "risk_confirmation") || "ambiguous",
          options: p?.options as ClarificationOption[] | undefined,
          context: p?.context as string | undefined,
        });
        break;
      }

      default:
        if (import.meta.env.DEV) {
          console.debug("[StreamPipeline] ignored event", payloadType, payload);
        }
        break;
    }
  }

  function ensureReasoningContext(messageId: string): void {
    if (!reasoningContexts.value.has(messageId)) {
      reasoningContexts.value.set(messageId, {
        startedAt: Date.now(),
        content: "",
        completedAt: null,
        durationMs: null,
        status: "pending",
      });
    }
  }

  function completeReasoningLogic(messageId: string): void {
    const ctx = reasoningContexts.value.get(messageId);
    if (!ctx) return;
    ctx.completedAt = Date.now();
    ctx.durationMs = ctx.startedAt ? ctx.completedAt - ctx.startedAt : 0;
    ctx.status = "complete";
    callbacks.onReasonComplete?.(messageId, ctx.durationMs ?? 0);
  }

  function completeReasoning(messageId: string): void {
    completeReasoningLogic(messageId);
  }

  function pushEvent(eventType: string, payload: unknown): void {
    buffer.push(eventType, payload);
  }

  function reset(): void {
    buffer.destroy();
    reasoningContexts.value = new Map();
  }

  onUnmounted(() => {
    buffer.destroy();
  });

  return {
    pushEvent,
    completeReasoning,
    reset,
  };
}
