import { computed } from "vue";
import type { Ref } from "vue";
import type { ChatMessageItem } from "@/types/chat";

export interface MessageGroup {
  type: "user" | "assistant" | "processing";
  messages: ChatMessageItem[];
}

export function useMessageGroups(messages: Ref<ChatMessageItem[]>) {
  const groups = computed<MessageGroup[]>(() => {
    const result: MessageGroup[] = [];
    let currentGroup: MessageGroup | null = null;

    for (const msg of messages.value) {
      if (msg.role === "user") {
        currentGroup = { type: "user", messages: [msg] };
        result.push(currentGroup);
        currentGroup = null;
        continue;
      }

      const hasThinking = !!(msg.thinkingContent && msg.thinkingContent.trim());
      const hasToolCalls = !!(msg.toolCalls && msg.toolCalls.length > 0);
      const hasContent = !!(msg.content && msg.content.trim());

      if (hasThinking || hasToolCalls) {
        const processingGroup: MessageGroup = { type: "processing", messages: [msg] };
        result.push(processingGroup);
      }

      if (hasContent) {
        const assistantGroup: MessageGroup = { type: "assistant", messages: [msg] };
        result.push(assistantGroup);
      }

      if (!hasThinking && !hasToolCalls && !hasContent && msg.role === "assistant") {
        const processingGroup: MessageGroup = { type: "processing", messages: [msg] };
        result.push(processingGroup);
      }
    }

    return result;
  });

  return { groups };
}
