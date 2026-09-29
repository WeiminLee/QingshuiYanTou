import { describe, expect, it, vi, beforeEach } from "vitest";

const listTasks = vi.fn();

vi.mock("@/api/agent.js", () => ({
  listTasks,
}));

describe("useHistoryData", () => {
  beforeEach(() => {
    listTasks.mockReset();
  });

  it("filters history items without a readable question", async () => {
    listTasks.mockResolvedValue({
      items: [
        { task_id: "empty-1", question: "", updated_at: "2026-07-18T10:00:00Z" },
        { task_id: "blank-1", question: "   ", updated_at: "2026-07-18T09:00:00Z" },
        { task_id: "valid-1", question: "分析光模块赛道", updated_at: "2026-07-18T08:00:00Z" },
        { task_id: "missing-1", updated_at: "2026-07-18T07:00:00Z" },
      ],
    });

    const { useHistoryData } = await import("../src/composables/useHistoryData.ts");
    const history = useHistoryData();

    await history.load();

    expect(history.items.value).toEqual([
      { task_id: "valid-1", question: "分析光模块赛道", updated_at: "2026-07-18T08:00:00Z" },
    ]);
    expect(history.recent.value.map((item) => item.question)).toEqual(["分析光模块赛道"]);
  });
});
