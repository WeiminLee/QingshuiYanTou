import { describe, expect, it, vi, beforeEach } from "vitest";

const streamReport = vi.fn();

vi.mock("@/api/agent.js", () => ({
  streamReport,
  resolveClarification: vi.fn(),
}));

describe("useChatSession signal context", () => {
  beforeEach(() => {
    streamReport.mockReset();
    streamReport.mockResolvedValue({ task_id: "task-1" });
    globalThis.EventSource = class {
      constructor() {}
      addEventListener() {}
      close() {}
    };
  });

  it("forwards signal_id when sending a signal-backed question", async () => {
    const { useChatSession } = await import("../src/composables/useChatSession.ts");
    const session = useChatSession();

    await session.sendMessage("请分析这个信号", undefined, { signalId: "SIG:abc" });

    expect(streamReport).toHaveBeenCalledWith(
      expect.objectContaining({
        question: "请分析这个信号",
        signal_id: "SIG:abc",
      }),
    );
  });
});
