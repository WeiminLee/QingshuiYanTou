/**
 * SequenceReorderBuffer — SSE 事件重排缓冲区
 *
 * Ported from persona AgentWidget SequenceReorderBuffer。
 * 用于处理 SSE 事件乱序到达的场景（网络延迟、HTTP/2 多路复用）。
 *
 * 规则：
 * - 无 seq 字段 → 立即 emit（向后兼容）
 * - seq === nextExpectedSeq → emit + drain consecutive
 * - seq < nextExpectedSeq → emit immediately（重复或迟到）
 * - seq > nextExpectedSeq → buffer + 启动 50ms gap timer
 * - gap timer 到期 → flush 所有 buffer
 *
 * 性能约束：buffer.size <= 2000
 */

type BufferedEvent = {
  payloadType: string;
  payload: unknown;
  seq: number;
};

type EmitterFn = (payloadType: string, payload: unknown) => void;

export const DEFAULT_GAP_TIMEOUT_MS = 50;
export const MAX_BUFFER_SIZE = 2000;

export class SequenceReorderBuffer {
  private nextExpectedSeq: number | null = null;
  private buffer: Map<number, BufferedEvent> = new Map();
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private emitter: EmitterFn;
  private gapTimeoutMs: number;

  constructor(emitter: EmitterFn, gapTimeoutMs = DEFAULT_GAP_TIMEOUT_MS) {
    this.emitter = emitter;
    this.gapTimeoutMs = gapTimeoutMs;
  }

  /**
   * 接收一个 SSE 事件负载，决定是立即 emit 还是 buffer。
   * 从 payload 提取 seq 字段（兼容清水后端格式）。
   */
  push(payloadType: string, payload: unknown): void {
    // 从 payload 提取 seq 字段（兼容清水后端格式）
    const seq =
      (payload as Record<string, unknown>)?.seq ??
      (payload as Record<string, unknown>)?.sequenceIndex ??
      (payload as Record<string, unknown>)?.agentContext?.seq;

    // 无 seq → 立即 emit + flush buffer（向后兼容）
    if (seq === undefined || seq === null) {
      if (this.buffer.size > 0) {
        this.flushAll();
      }
      this.emitter(payloadType, payload);
      return;
    }

    // 初始化 nextExpectedSeq
    if (this.nextExpectedSeq === null) {
      this.nextExpectedSeq = 1;
    }

    // seq === 期望值 → emit + drain consecutive
    if (seq === this.nextExpectedSeq) {
      this.emitter(payloadType, payload);
      this.nextExpectedSeq = (seq as number) + 1;
      this.drainConsecutive();
      return;
    }

    // seq < 期望值 → 立即 emit（重复或迟到，不丢弃）
    if (seq < this.nextExpectedSeq!) {
      this.emitter(payloadType, payload);
      return;
    }

    // seq > 期望值 → buffer
    // 溢出保护
    if (this.buffer.size >= MAX_BUFFER_SIZE) {
      console.warn("[SequenceReorderBuffer] buffer overflow, flushing oldest");
      this.flushAll();
    }

    // 如果已有相同 seq，先 emit 已有事件（避免丢失）
    const existing = this.buffer.get(seq as number);
    if (existing !== undefined) {
      this.emitter(existing.payloadType, existing.payload);
    }
    this.buffer.set(seq as number, { payloadType, payload, seq: seq as number });
    this.startGapTimer();
  }

  private drainConsecutive(): void {
    while (this.buffer.has(this.nextExpectedSeq!)) {
      const event = this.buffer.get(this.nextExpectedSeq!)!;
      this.buffer.delete(this.nextExpectedSeq!);
      this.emitter(event.payloadType, event.payload);
      this.nextExpectedSeq!++;
    }
    if (this.buffer.size === 0) {
      this.clearGapTimer();
    }
  }

  private startGapTimer(): void {
    if (this.flushTimer !== null) return;
    this.flushTimer = setTimeout(() => {
      this.flushAll();
    }, this.gapTimeoutMs);
  }

  private clearGapTimer(): void {
    if (this.flushTimer !== null) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
  }

  private flushAll(): void {
    this.clearGapTimer();
    if (this.buffer.size === 0) return;

    const sorted = [...this.buffer.entries()].sort((a, b) => a[0] - b[0]);
    for (const [seq, event] of sorted) {
      this.buffer.delete(seq);
      this.emitter(event.payloadType, event.payload);
    }
    if (sorted.length > 0) {
      this.nextExpectedSeq = sorted[sorted.length - 1][0] + 1;
    }
  }

  /** 销毁缓冲区，清理 timer */
  destroy(): void {
    this.clearGapTimer();
    this.buffer.clear();
  }

  /** 强制 flush 所有缓冲事件 */
  flushPending(): void {
    this.flushAll();
  }

  /** 暴露 buffer size 供测试 */
  get bufferSize(): number {
    return this.buffer.size;
  }
}
