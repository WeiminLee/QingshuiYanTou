import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listSignals = vi.fn();
const getSignalDetail = vi.fn();
const updateSignalStatus = vi.fn();

vi.mock("@/api/signals.js", () => ({
  listSignals,
  getSignalDetail,
  updateSignalStatus,
}));

describe("SignalRadar", () => {
  beforeEach(() => {
    listSignals.mockReset();
    getSignalDetail.mockReset();
    updateSignalStatus.mockReset();
    listSignals.mockResolvedValue({
      items: [
        {
          signal_id: "SIG:abc",
          title: "800G 光模块规模量产",
          summary: "量产确认 -> 订单兑现 -> 供应链需求增强",
          source_type: "announcement",
          value_score: 92,
          confidence: 0.92,
          portfolio_hits: ["中际旭创"],
        },
      ],
      total: 1,
    });
    getSignalDetail.mockResolvedValue({
      signal_id: "SIG:abc",
      title: "800G 光模块规模量产",
      value_score: 92,
      confidence: 0.92,
      evidence_excerpt: "相关产品已进入规模量产阶段",
      portfolio_hits: ["中际旭创"],
      propagations: [
        {
          relation_path: "量产确认 -> 订单兑现概率提升 -> 供应链需求增强",
          reasoning: "高速光模块放量可能提升上游需求",
        },
      ],
    });
  });

  it("renders signal title and score", async () => {
    const { default: SignalRadar } = await import("../src/components/SignalRadar.vue");
    const wrapper = mount(SignalRadar);
    await flushPromises();

    expect(wrapper.text()).toContain("800G 光模块规模量产");
    expect(wrapper.text()).toContain("92");
  });

  it("pauses on hover and resumes on leave", async () => {
    const { default: SignalRadar } = await import("../src/components/SignalRadar.vue");
    const wrapper = mount(SignalRadar);
    await flushPromises();

    await wrapper.find(".signal-radar").trigger("mouseenter");
    expect(wrapper.find(".signal-radar").classes()).toContain("is-paused");

    await wrapper.find(".signal-radar").trigger("mouseleave");
    expect(wrapper.find(".signal-radar").classes()).not.toContain("is-paused");
  });

  it("opens detail and emits ask-signal", async () => {
    const { default: SignalRadar } = await import("../src/components/SignalRadar.vue");
    const wrapper = mount(SignalRadar);
    await flushPromises();

    await wrapper.find(".signal-card").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("相关产品已进入规模量产阶段");

    await wrapper.find('[data-testid="ask-signal"]').trigger("click");
    expect(wrapper.emitted("ask-signal")[0][0]).toEqual({
      signalId: "SIG:abc",
      question: "请结合我的持仓，分析这个信号的预期差、传导逻辑、可能受益/受损对象和主要风险。",
    });
  });

  it("renders catalyst alert fields", async () => {
    listSignals.mockResolvedValueOnce({
      items: [
        {
          signal_id: "SIG:cat",
          title: "未来5天英伟达GTC可能影响AI算力链",
          summary: "海外 AI 算力大会可能影响光模块/CPO 链预期",
          source_type: "catalyst_event",
          signal_kind: "catalyst",
          value_score: 86,
          confidence: 0.72,
          portfolio_hits: ["中际旭创", "新易盛"],
          lead_days: 5,
          alert_level: "high",
          impact_scope: ["portfolio", "market"],
        },
      ],
      total: 1,
    });
    const { default: SignalRadar } = await import("../src/components/SignalRadar.vue");
    const wrapper = mount(SignalRadar);
    await flushPromises();

    expect(wrapper.text()).toContain("未来预警");
    expect(wrapper.text()).toContain("5天后");
    expect(wrapper.text()).toContain("持仓 2");
  });

  it("loads catalyst filter with five day window", async () => {
    const { default: SignalRadar } = await import("../src/components/SignalRadar.vue");
    const wrapper = mount(SignalRadar);
    await flushPromises();

    await wrapper.find('[data-testid="signal-kind-catalyst"]').trigger("click");
    await flushPromises();

    expect(listSignals).toHaveBeenLastCalledWith({
      scope: "all",
      limit: 8,
      signal_kind: "catalyst",
      window_days: 5,
    });
  });
});

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}
