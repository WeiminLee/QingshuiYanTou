import { describe, expect, it, vi, beforeEach } from "vitest";

const streamReport = vi.fn();

vi.mock("@/api/agent.js", () => ({
  streamReport,
  resolveClarification: vi.fn(),
}));

vi.mock("../src/composables/useMockAgentStream.ts", () => ({
  runMockAgentStream: vi.fn(async (_question, handlers) => {
    handlers.onReasoningStart?.();
    handlers.onThinking?.("正在分析问题。");
    handlers.onToolStart?.({
      id: "mock-tool",
      name: "mock_search",
      status: "running",
      args: { keyword: "测试" },
    });
    handlers.onToolEnd?.("mock-tool", "模拟工具结果", 120, "模拟工具摘要");
    handlers.onContent?.("### Mock 输出\n\n工具调用展示正常。");
    handlers.onComplete?.();
  }),
}));

describe("useChatSession mock agent mode", () => {
  beforeEach(() => {
    streamReport.mockReset();
    vi.stubEnv("VITE_USE_MOCK_AGENT", "true");
  });

  it("renders a local mock stream without calling the backend", async () => {
    const { useChatSession } = await import("../src/composables/useChatSession.ts");
    const session = useChatSession();

    await session.sendMessage("测试工具调用展示");

    expect(streamReport).not.toHaveBeenCalled();
    expect(session.isLoading.value).toBe(false);
    expect(session.messages.value).toHaveLength(2);

    const assistant = session.messages.value[1];
    expect(assistant.content).toContain("Mock 输出");
    expect(assistant.toolCalls).toEqual([
      expect.objectContaining({
        id: "mock-tool",
        name: "mock_search",
        status: "done",
        result: "模拟工具结果",
        preview: "模拟工具摘要",
      }),
    ]);
  });
});
