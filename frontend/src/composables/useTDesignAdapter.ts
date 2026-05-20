/**
 * useTDesignAdapter — ChatMessageItem[] → t-chat items 适配器
 *
 * 单一展开状态管理：
 * - expansionState 管理 per-message 展开状态 + 延迟自动折叠
 * - isExpanded / expand / collapse / toggleExpand / scheduleAutoCollapse 全部在此定义
 * - useChatSession.onReasonComplete 回调中调用 scheduleAutoCollapse，
 *   由 useTDesignAdapter 统一管理状态（不再各自维护独立 Map）
 */
import { ref, computed, onUnmounted, type Ref } from 'vue'
import type { ChatMessageItem } from '@/types/chat'

export interface TDesignChatItem {
  id: string
  role: 'user' | 'assistant'
  avatar?: string
  name?: string
  datetime?: string
  content?: string
  placement?: 'left' | 'right'
  variant?: 'base' | 'outline' | 'text'
  reasoning?: {
    content: string
    collapsed: boolean
  }
}

const AUTO_COLLAPSE_DELAY_MS = 1000

export function useTDesignAdapter(messages: Ref<ChatMessageItem[]>) {
  // Per-message expansion state map: messageId -> isExpanded
  const expansionMap = ref<Map<string, boolean>>(new Map())

  // 延迟折叠定时器（避免内存泄漏）
  const collapseTimers = new Map<string, ReturnType<typeof setTimeout>>()

  // 默认 true：流式过程中 thinking 面板可见；scheduleAutoCollapse 后变为 false（折叠）
  function isExpanded(messageId: string): boolean {
    return expansionMap.value.get(messageId) ?? true
  }

  function expand(messageId: string): void {
    expansionMap.value = new Map(expansionMap.value).set(messageId, true)
  }

  function collapse(messageId: string): void {
    expansionMap.value = new Map(expansionMap.value).set(messageId, false)
  }

  function toggleExpand(messageId: string): void {
    expansionMap.value = new Map(expansionMap.value).set(messageId, !isExpanded(messageId))
  }

  /**
   * 调度延迟折叠（推理完成后自动折叠 thinking 面板）。
   * 由 useChatSession.onReasonComplete 回调调用。
   */
  function scheduleAutoCollapse(messageId: string, delayMs: number = AUTO_COLLAPSE_DELAY_MS): void {
    const existing = collapseTimers.get(messageId)
    if (existing) clearTimeout(existing)
    const timer = setTimeout(() => {
      collapse(messageId)
      collapseTimers.delete(messageId)
    }, delayMs)
    collapseTimers.set(messageId, timer)
  }

  // 组件卸载时清理定时器
  onUnmounted(() => {
    collapseTimers.forEach(t => clearTimeout(t))
    collapseTimers.clear()
  })

  // t-chat data items
  const tdesignItems = computed<TDesignChatItem[]>(() =>
    messages.value.map(msg => {
      const ts = msg.timestamp
      const datetime = ts ? new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''

      if (msg.role === 'user') {
        return {
          id: msg.id,
          role: 'user' as const,
          name: '你',
          avatar: '',
          datetime,
          content: msg.content,
          placement: 'right',
          variant: 'base',
        }
      }

      // assistant
      const reasoningCollapsed = !isExpanded(msg.id)
      return {
        id: msg.id,
        role: 'assistant' as const,
        name: '观仓 AI',
        avatar: '',
        datetime,
        content: msg.content,
        reasoning: msg.thinkingContent
          ? { content: msg.thinkingContent, collapsed: reasoningCollapsed }
          : undefined,
      }
    })
  )

  return {
    tdesignItems,
    expansionMap,
    isExpanded,
    expand,
    collapse,
    toggleExpand,
    scheduleAutoCollapse,
  }
}
