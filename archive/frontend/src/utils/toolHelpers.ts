/**
 * Tool call display utilities — shared by ToolCallStep, ToolCallChain, etc.
 * Extracted from useStreamingRenderer.js for clean separation.
 */

import {
  LineChart,
  Flame,
  BarChart3,
  Network,
  FileSearch,
  FileText,
  Search,
  Building2,
  MessageCircle,
  PieChart,
  ListChecks,
  HelpCircle,
  Globe,
  Folder,
  FileEdit,
  Wrench,
} from "lucide-vue-next";
import type { Component } from "vue";

/** Map tool names to friendly Chinese labels */
export function normalizeToolName(name) {
  const map = {
    get_kline: "K线行情",
    get_concept_hot: "概念热度",
    get_market_breadth: "市场宽度",
    neo4j_traverse: "知识图谱",
    neo4j_kg_search: "图谱搜索",
    get_research_report: "研报检索",
    get_announcement: "公告查询",
    tavily_search: "网络搜索",
    get_stock_profile: "公司画像",
    get_irm: "投资者关系",
    present_chart: "图表展示",
    write_todos: "待办更新",
    ask_clarification: "需求澄清",
    web_fetch: "网页抓取",
    ls: "浏览文件",
    read_file: "读取文件",
    write_file: "写入文件",
  };
  return map[name] || name || "工具调用";
}

/** Map tool names to Lucide icon components (per Phase 23 P23-A) */
export function getToolIcon(name: string): Component {
  const map: Record<string, Component> = {
    get_kline: LineChart,
    get_concept_hot: Flame,
    get_market_breadth: BarChart3,
    neo4j_traverse: Network,
    neo4j_kg_search: Network,
    get_research_report: FileSearch,
    get_announcement: FileText,
    tavily_search: Search,
    get_stock_profile: Building2,
    get_irm: MessageCircle,
    present_chart: PieChart,
    write_todos: ListChecks,
    ask_clarification: HelpCircle,
    web_fetch: Globe,
    ls: Folder,
    read_file: FileSearch,
    write_file: FileEdit,
  };
  return map[name] || Wrench;
}

/** Format tool args for display */
export function formatToolArgs(args) {
  if (!args) return "";
  try {
    const parsed = typeof args === "string" ? JSON.parse(args) : args;
    const entries = Object.entries(parsed);
    if (entries.length === 0) return "";
    return entries
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
      .join(" | ");
  } catch {
    return String(args);
  }
}

/** Format milliseconds to human-readable duration */
export function formatDuration(ms) {
  if (!ms || ms < 0) return "";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}秒`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return secs > 0 ? `${minutes}分${secs}秒` : `${minutes}分钟`;
}

/** Check if tool result contains kline data */
export function isKlineData(result) {
  if (!result) return false;
  try {
    const parsed = typeof result === "string" ? JSON.parse(result) : result;
    return (
      Array.isArray(parsed?.data) && parsed.data.length > 0 && parsed.data[0]?.close !== undefined
    );
  } catch {
    return false;
  }
}

/** Compute elapsed time between two timestamps */
export function computeToolElapsed(startTime, endTime) {
  if (!startTime || !endTime) return null;
  return endTime - startTime;
}
