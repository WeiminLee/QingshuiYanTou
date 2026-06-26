/**
 * useExpansionState — 每条消息的展开状态管理
 *
 * 功能：
 * - per-message expansion state via Map<messageId, boolean>
 * - immutable update pattern (new Map each time)
 * - auto-collapse with configurable delay
 * - onUnmounted cleanup of all timers
 *
 * 引用：ThinkingPanel.vue 的 AUTO_COLLAPSE_DELAY_MS = 1000
 */

import { ref, onUnmounted } from "vue";

/** 展开状态 map 的类型 */
export type ExpansionMap = Map<string, boolean>;

/** useExpansionState 返回类型 */
export interface UseExpansionStateReturn {
  /** 消息展开状态 map */
  expansionMap: ReturnType<typeof ref<ExpansionMap>>["value"];
  /** 查询消息是否展开 */
  isExpanded: (msgId: string) => boolean;
  /** 展开指定消息 */
  expand: (msgId: string) => void;
  /** 折叠指定消息 */
  collapse: (msgId: string) => void;
  /** 切换展开状态 */
  toggle: (msgId: string) => void;
  /** 调度延迟折叠（默认 1000ms） */
  scheduleAutoCollapse: (msgId: string, delayMs?: number) => void;
  /** 取消延迟折叠 */
  cancelAutoCollapse: (msgId: string) => void;
  /** 清除所有状态和定时器 */
  clear: () => void;
}

const AUTO_COLLAPSE_DELAY_MS = 1000;

export function useExpansionState(): UseExpansionStateReturn {
  /** 展开状态 map，immutable update pattern */
  const expansionMap = ref<ExpansionMap>(new Map());

  /** 延迟折叠定时器 map */
  const collapseTimers = new Map<string, ReturnType<typeof setTimeout>>();

  /**
   * 查询消息是否展开
   */
  function isExpanded(msgId: string): boolean {
    return expansionMap.value.get(msgId) ?? false;
  }

  /**
   * 展开指定消息
   * immutable: 创建新的 Map
   */
  function expand(msgId: string): void {
    expansionMap.value = new Map(expansionMap.value).set(msgId, true);
  }

  /**
   * 折叠指定消息
   * immutable: 创建新的 Map
   */
  function collapse(msgId: string): void {
    expansionMap.value = new Map(expansionMap.value).set(msgId, false);
  }

  /**
   * 切换展开状态
   */
  function toggle(msgId: string): void {
    const current = isExpanded(msgId);
    expansionMap.value = new Map(expansionMap.value).set(msgId, !current);
  }

  /**
   * 调度延迟折叠
   * - 如果已存在该消息的定时器，先取消再创建
   */
  function scheduleAutoCollapse(msgId: string, delayMs: number = AUTO_COLLAPSE_DELAY_MS): void {
    cancelAutoCollapse(msgId);
    const timer = setTimeout(() => {
      collapse(msgId);
      collapseTimers.delete(msgId);
    }, delayMs);
    collapseTimers.set(msgId, timer);
  }

  /**
   * 取消延迟折叠
   */
  function cancelAutoCollapse(msgId: string): void {
    const existing = collapseTimers.get(msgId);
    if (existing) {
      clearTimeout(existing);
      collapseTimers.delete(msgId);
    }
  }

  /**
   * 清除所有状态和定时器
   */
  function clear(): void {
    // 清除所有定时器
    collapseTimers.forEach((timer) => clearTimeout(timer));
    collapseTimers.clear();
    // 重置 map
    expansionMap.value = new Map();
  }

  /**
   * 组件卸载时清理所有定时器
   */
  onUnmounted(() => {
    collapseTimers.forEach((timer) => clearTimeout(timer));
    collapseTimers.clear();
  });

  return {
    expansionMap,
    isExpanded,
    expand,
    collapse,
    toggle,
    scheduleAutoCollapse,
    cancelAutoCollapse,
    clear,
  };
}
