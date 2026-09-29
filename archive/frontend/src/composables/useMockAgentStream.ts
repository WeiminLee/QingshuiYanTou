import type { ToolCallItem } from "@/types/chat";

export interface MockAgentStreamHandlers {
  onReasoningStart?: () => void;
  onThinking?: (delta: string) => void;
  onToolStart?: (toolCall: ToolCallItem) => void;
  onToolEnd?: (toolId: string, result: string, durationMs: number, preview?: string) => void;
  onContent?: (content: string) => void;
  onComplete?: () => void;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function runMockAgentStream(
  question: string,
  handlers: MockAgentStreamHandlers,
): Promise<void> {
  handlers.onReasoningStart?.();
  await sleep(80);

  for (const delta of [
    "我会先识别问题中的研究对象和关注点，",
    "再模拟调用本地数据、知识图谱和证据检索工具，",
    "最后把结论整理成可读的投研摘要。\n\n",
  ]) {
    handlers.onThinking?.(delta);
    await sleep(120);
  }

  handlers.onToolStart?.({
    id: "mock-tool-stock-profile",
    name: "get_company_profile",
    status: "running",
    args: { query: question, scope: "mock" },
  });
  await sleep(450);
  handlers.onToolEnd?.(
    "mock-tool-stock-profile",
    JSON.stringify({
      company: "示例公司",
      industry: "光通信",
      signals: ["订单弹性", "毛利率修复", "客户结构变化"],
    }),
    438,
    "示例公司：光通信产业链；关注订单弹性、毛利率修复和客户结构变化。",
  );

  handlers.onToolStart?.({
    id: "mock-tool-evidence",
    name: "search_evidence",
    status: "running",
    args: { keyword: "预期差", limit: 3 },
  });
  await sleep(420);
  handlers.onToolEnd?.(
    "mock-tool-evidence",
    "找到 3 条模拟证据：1. 近期订单节奏改善；2. 上游成本压力缓解；3. 下游 AI 需求仍有不确定性。",
    421,
    "找到 3 条模拟证据，覆盖订单、成本和需求三个维度。",
  );

  await sleep(180);
  handlers.onContent?.(
    [
      `针对“${question}”，这是本地 mock agent 的前端联调输出。`,
      "",
      "### 初步判断",
      "当前展示链路已覆盖流式文本、工具调用、工具结果和最终 Markdown 输出。真实数据库为空时，可以先用这个模式检查前端状态是否稳定。",
      "",
      "### 观察点",
      "- 工具调用应按运行中到完成的状态更新。",
      "- 工具结果摘要应能正常展示和展开。",
      "- 最终答案应替换流式增量内容，保持 Markdown 排版。",
      "",
      "### 下一步",
      "确认 UI 正常后，再切换到真实后端 Agent，并灌入少量样本数据验证真实工具结果。",
    ].join("\n"),
  );
  handlers.onComplete?.();
}
