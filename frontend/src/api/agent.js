/**
 * Agent 分析 API
 */
import apiClient from "./index.js";

// 发起流式报告任务
export const streamReport = (params) =>
  apiClient.post("/agent/stream/report", {
    ...params,
    thread_id: params.thread_id || undefined,
  });

// 查询任务状态（含完整报告 JSON）
export const getTaskResult = (taskId) =>
  apiClient.get(`/agent/invoke/${taskId}/result`).then((res) => {
    const d = res.data || res;
    return {
      taskId: d.task_id,
      status: d.status,
      content: d.content,
      reportJson: d.report_json || null,
      reportContent: d.report_content || d.content || "",
      reportId: d.report_id || null,
      compliancePassed: d.compliance_passed ?? null,
    };
  });

// 列出最近任务
export const listTasks = (limit = 20) =>
  apiClient
    .get("/agent/invoke", {
      params: { limit },
      // 历史列表属于辅助信息，单独设置更短超时，避免拖累主流程
      timeout: 8000,
    })
    .catch(() => ({ items: [] }));

// 澄清请求 - 用户回复
export async function resolveClarification(taskId, { answer, clarification_id }) {
  const resp = await fetch(`/api/v1/agent/resolve/${taskId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer, clarification_id }),
  });
  if (!resp.ok) throw new Error(`resolveClarification failed: ${resp.status}`);
  return resp.json();
}

// 直接返回报告（同步接口）
export const chatQuestion = (params) => apiClient.post("/agent/chat", params);

// 生成报告（同步接口）
export const generateReport = (params) => apiClient.post("/agent/report", params);
