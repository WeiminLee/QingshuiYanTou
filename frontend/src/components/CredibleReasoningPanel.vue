<template>
  <section v-if="visible" class="credible-panel" aria-label="可信推理链">
    <header class="credible-header">
      <div>
        <div class="credible-kicker">可信推理链</div>
        <h2>证据、图谱与来源校验</h2>
      </div>
      <div class="trace-status" :class="{ 'trace-status--running': isLoading }">
        <span class="trace-status-dot" />
        {{ isLoading ? "推理进行中" : "推理已归档" }}
      </div>
    </header>

    <div class="trace-metrics">
      <div class="trace-metric">
        <span class="metric-value">{{ completedToolCount }}</span>
        <span class="metric-label">完成工具</span>
      </div>
      <div class="trace-metric">
        <span class="metric-value">{{ sourceGroups.length }}</span>
        <span class="metric-label">来源层</span>
      </div>
      <div class="trace-metric">
        <span class="metric-value">{{ graphRelationCountText }}</span>
        <span class="metric-label">图谱关系</span>
      </div>
      <div class="trace-metric">
        <span class="metric-value">{{ evidenceItems.length }}</span>
        <span class="metric-label">结构化证据</span>
      </div>
    </div>

    <div class="trace-grid">
      <div class="trace-column">
        <div class="column-title">
          <Network :size="15" :stroke-width="1.7" />
          推理取证路径
        </div>
        <div v-if="reasoningExcerpt" class="reasoning-excerpt">
          <div class="reasoning-excerpt-label">过程摘录</div>
          <p>{{ reasoningExcerpt }}</p>
        </div>
        <div class="source-stack">
          <div v-for="group in sourceGroups" :key="group.key" class="source-group">
            <div class="source-group-head">
              <component :is="group.icon" :size="15" :stroke-width="1.7" />
              <span>{{ group.label }}</span>
              <span class="source-count">{{ group.items.length }}</span>
            </div>
            <div class="source-items">
              <div v-for="item in group.items" :key="item.id" class="source-item">
                <div class="source-item-main">
                  <span class="source-name">{{ item.name }}</span>
                  <span class="source-state" :class="`source-state--${item.status}`">
                    {{ statusText(item.status) }}
                  </span>
                </div>
                <div v-if="item.preview" class="source-preview">{{ item.preview }}</div>
                <div v-if="item.argsText" class="source-meta">{{ item.argsText }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="trace-column">
        <div class="column-title">
          <ShieldCheck :size="15" :stroke-width="1.7" />
          证据元数据
        </div>
        <div v-if="evidenceItems.length" class="evidence-stack">
          <div v-for="item in evidenceItems" :key="item.id" class="evidence-item">
            <div class="evidence-head">
              <span class="evidence-source">{{ item.sourceName }}</span>
              <span class="confidence-badge">{{ item.confidence || "未标注" }}</span>
            </div>
            <p>{{ item.content }}</p>
            <div class="evidence-meta">
              <span>{{ item.sourceType || "source" }}</span>
              <span v-if="item.timestamp">{{ item.timestamp }}</span>
            </div>
          </div>
        </div>
        <div v-else class="evidence-empty">
          <Database :size="16" :stroke-width="1.7" />
          <span>当前报告使用工具调用记录作为可追溯依据，结构化 Evidence 字段尚未返回。</span>
        </div>

        <div v-if="reportId || generatedAt" class="report-meta">
          <span v-if="reportId">报告ID {{ reportId }}</span>
          <span v-if="generatedAt">{{ generatedAt }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import {
  BarChart3,
  Building2,
  Database,
  FileSearch,
  FileText,
  Globe,
  MessageCircle,
  Network,
  Search,
  ShieldCheck,
} from "lucide-vue-next";
import type { Component } from "vue";
import type { ToolCallItem } from "@/types/chat";
import { formatToolArgs, normalizeToolName } from "@/utils/toolHelpers";

type ReportJson = Record<string, any> | null | undefined;

interface SourceItem {
  id: string;
  name: string;
  status: ToolCallItem["status"];
  preview: string;
  argsText: string;
  groupKey: string;
}

interface SourceGroup {
  key: string;
  label: string;
  icon: Component;
  items: SourceItem[];
}

interface EvidenceItem {
  id: string;
  sourceName: string;
  sourceType: string;
  content: string;
  confidence: string;
  timestamp: string;
}

const props = withDefaults(
  defineProps<{
    toolCalls?: ToolCallItem[];
    reportJson?: ReportJson;
    reasoningText?: string;
    isLoading?: boolean;
  }>(),
  {
    toolCalls: () => [],
    reportJson: null,
    reasoningText: "",
    isLoading: false,
  },
);

const GROUP_META: Record<string, { label: string; icon: Component }> = {
  graph: { label: "知识图谱", icon: Network },
  disclosure: { label: "公告与公司披露", icon: FileText },
  research: { label: "研报与外部研究", icon: FileSearch },
  market: { label: "行情与市场数据", icon: BarChart3 },
  profile: { label: "公司画像", icon: Building2 },
  web: { label: "公开网络来源", icon: Globe },
  interaction: { label: "投资者关系", icon: MessageCircle },
  background: { label: "向量背景知识", icon: Database },
  other: { label: "辅助工具", icon: Search },
};

const completedToolCount = computed(() =>
  Math.max(
    props.toolCalls.filter((tc) => tc.status === "done").length,
    Number(props.reportJson?.trace_summary?.successful_tool_count || 0),
  ),
);

const sourceItems = computed<SourceItem[]>(() =>
  props.toolCalls.map((tc, index) => ({
    id: tc.id || `${tc.name}-${index}`,
    name: normalizeToolName(tc.name),
    status: tc.status,
    preview: tc.preview || tc.result || "",
    argsText: formatToolArgs(tc.args || {}),
    groupKey: classifyTool(tc.name),
  })),
);

const sourceGroups = computed<SourceGroup[]>(() => {
  const buckets = new Map<string, SourceItem[]>();
  for (const item of sourceItems.value) {
    const existing = buckets.get(item.groupKey) || [];
    existing.push(item);
    buckets.set(item.groupKey, existing);
  }
  const reportLayers = Array.isArray(props.reportJson?.source_layers) ? props.reportJson.source_layers : [];
  for (const layer of reportLayers) {
    const key = String(layer?.key || "other");
    const existing = buckets.get(key) || [];
    const items = Array.isArray(layer?.items) ? layer.items : [];
    items.forEach((item: any, index: number) => {
      const tool = String(item?.tool || "trace");
      const id = String(item?.tool_call_id || `${key}-${index}`);
      if (existing.some((sourceItem) => sourceItem.id === id)) return;
      existing.push({
        id,
        name: tool === "pre_search" ? "预检索背景" : normalizeToolName(tool),
        status: item?.success === false ? "error" : "done",
        preview: String(item?.preview || ""),
        argsText: "",
        groupKey: key,
      });
    });
    if (existing.length > 0) {
      buckets.set(key, existing);
    }
  }
  const orderedKeys = [
    "graph",
    "disclosure",
    "interaction",
    "research",
    "market",
    "profile",
    "web",
    "background",
    "other",
  ];
  return orderedKeys
    .filter((key) => buckets.has(key))
    .map((key) => ({
      key,
      label: GROUP_META[key]?.label || key,
      icon: GROUP_META[key]?.icon || Search,
      items: buckets.get(key) || [],
    }));
});

const evidenceItems = computed<EvidenceItem[]>(() => {
  const conclusions = Array.isArray(props.reportJson?.conclusions) ? props.reportJson?.conclusions : [];
  const items: EvidenceItem[] = [];
  const reportEvidence = Array.isArray(props.reportJson?.evidence_refs) ? props.reportJson.evidence_refs : [];
  reportEvidence.forEach((ev: any, index: number) => {
    const content = String(ev?.content || "").trim();
    if (!content) return;
    items.push({
      id: String(ev?.id || `trace-${index}`),
      sourceName: String(ev?.source_name || ev?.tool || "推理来源"),
      sourceType: String(ev?.source_type || ""),
      content: content.length > 140 ? `${content.slice(0, 140)}...` : content,
      confidence: String(ev?.confidence || ""),
      timestamp: String(ev?.timestamp || ""),
    });
  });
  conclusions.forEach((conclusion: any, conclusionIndex: number) => {
    const evidence = Array.isArray(conclusion?.evidence) ? conclusion.evidence : [];
    evidence.forEach((ev: any, evidenceIndex: number) => {
      const content = String(ev?.content || "").trim();
      if (!content) return;
      items.push({
        id: `${conclusion?.id || conclusionIndex}-${evidenceIndex}`,
        sourceName: String(ev?.source_name || "未知来源"),
        sourceType: String(ev?.source_type || ""),
        content: content.length > 140 ? `${content.slice(0, 140)}...` : content,
        confidence: String(ev?.confidence || ""),
        timestamp: String(ev?.timestamp || ""),
      });
    });
  });
  return items.slice(0, 6);
});

const graphRelationCount = computed(() => {
  let count = 0;
  const graphRefs = Array.isArray(props.reportJson?.graph_refs) ? props.reportJson.graph_refs : [];
  for (const ref of graphRefs) {
    const n = Number(ref?.relation_count || 0);
    if (Number.isFinite(n)) count += n;
  }
  for (const tc of props.toolCalls) {
    if (!["neo4j_traverse", "neo4j_kg_search"].includes(tc.name)) continue;
    const text = `${tc.preview || ""} ${tc.result || ""}`;
    const match = text.match(/(\d+)\s*条(?:关系|结果)?/);
    if (match) count += Number(match[1] || 0);
  }
  return count;
});

const graphRelationCountText = computed(() => (graphRelationCount.value > 0 ? String(graphRelationCount.value) : "-"));

const reportId = computed(() => props.reportJson?.report_id || "");
const generatedAt = computed(() => props.reportJson?.generated_at || "");
const reasoningExcerpt = computed(() => {
  const text = props.reasoningText.replace(/\[ASK_CLARIFICATION\][\s\S]*$/g, "").trim();
  if (!text) return "";
  const compact = text.replace(/\s+/g, " ");
  return compact.length > 180 ? `${compact.slice(0, 180)}...` : compact;
});
const visible = computed(
  () =>
    props.isLoading ||
    props.toolCalls.length > 0 ||
    sourceGroups.value.length > 0 ||
    evidenceItems.value.length > 0 ||
    Boolean(reasoningExcerpt.value),
);

function classifyTool(name = ""): string {
  if (name.includes("neo4j")) return "graph";
  if (["get_announcement"].includes(name)) return "disclosure";
  if (["get_irm"].includes(name)) return "interaction";
  if (["get_research_report"].includes(name)) return "research";
  if (["get_kline", "get_concept_hot", "get_market_breadth"].includes(name)) return "market";
  if (["get_stock_profile"].includes(name)) return "profile";
  if (["tavily_search", "web_fetch"].includes(name)) return "web";
  return "other";
}

function statusText(status: ToolCallItem["status"]): string {
  const map: Record<ToolCallItem["status"], string> = {
    pending: "等待",
    running: "执行中",
    done: "完成",
    error: "失败",
  };
  return map[status] || status;
}
</script>

<style scoped>
.credible-panel {
  border: 1px solid rgba(184, 134, 11, 0.28);
  background: linear-gradient(180deg, rgba(250, 250, 247, 0.96) 0%, rgba(245, 242, 235, 0.96) 100%);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 18px;
  box-shadow: 0 8px 24px rgba(26, 24, 20, 0.06);
}

.credible-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.credible-kicker {
  font-size: 12px;
  line-height: 1.4;
  color: var(--ledger-gold);
  font-weight: 700;
}

.credible-header h2 {
  margin: 2px 0 0;
  font-family: var(--font-display);
  font-size: 18px;
  line-height: 1.35;
  color: var(--ledger-ink);
  letter-spacing: 0;
}

.trace-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 9px;
  border: 1px solid rgba(45, 158, 108, 0.22);
  border-radius: 6px;
  background: rgba(45, 158, 108, 0.08);
  color: var(--status-success);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.trace-status--running {
  border-color: rgba(59, 91, 219, 0.22);
  background: rgba(59, 91, 219, 0.08);
  color: var(--ledger-blue);
}

.trace-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentColor;
}

.trace-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.trace-metric {
  border: 1px solid var(--ledger-rule);
  background: rgba(255, 255, 255, 0.44);
  border-radius: 6px;
  padding: 10px 12px;
  min-width: 0;
}

.metric-value {
  display: block;
  color: var(--ledger-ink);
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 800;
  line-height: 1.1;
}

.metric-label {
  display: block;
  margin-top: 4px;
  color: var(--text-main-3);
  font-size: 12px;
}

.trace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
  gap: 14px;
}

.trace-column {
  min-width: 0;
}

.column-title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--ledger-ink);
  font-size: 13px;
  font-weight: 800;
  margin-bottom: 8px;
}

.column-title svg {
  color: var(--ledger-gold);
}

.source-stack,
.evidence-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.reasoning-excerpt {
  border: 1px solid rgba(59, 91, 219, 0.18);
  border-radius: 6px;
  background: rgba(59, 91, 219, 0.055);
  padding: 10px 11px;
  margin-bottom: 8px;
}

.reasoning-excerpt-label {
  color: var(--ledger-blue);
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 5px;
}

.reasoning-excerpt p {
  margin: 0;
  color: var(--text-main-2);
  font-size: 12px;
  line-height: 1.6;
}

.source-group {
  border: 1px solid var(--ledger-rule);
  border-radius: 6px;
  overflow: hidden;
  background: rgba(250, 250, 247, 0.82);
}

.source-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 11px;
  border-bottom: 1px solid var(--ledger-rule);
  color: var(--ledger-ink);
  font-size: 13px;
  font-weight: 800;
}

.source-group-head svg {
  color: var(--ledger-blue);
  flex-shrink: 0;
}

.source-count {
  margin-left: auto;
  min-width: 22px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  background: rgba(59, 91, 219, 0.08);
  color: var(--ledger-blue);
  font-family: var(--font-mono);
  font-size: 12px;
}

.source-items {
  display: flex;
  flex-direction: column;
}

.source-item {
  padding: 10px 11px;
}

.source-item + .source-item {
  border-top: 1px solid rgba(212, 207, 196, 0.65);
}

.source-item-main,
.evidence-head,
.evidence-meta,
.report-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.source-name {
  color: var(--ledger-ink);
  font-size: 13px;
  font-weight: 700;
}

.source-state,
.confidence-badge {
  margin-left: auto;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.source-state--done {
  color: var(--status-success);
  background: rgba(45, 158, 108, 0.09);
}

.source-state--running,
.source-state--pending {
  color: var(--ledger-blue);
  background: rgba(59, 91, 219, 0.09);
}

.source-state--error {
  color: var(--ledger-red);
  background: rgba(192, 57, 43, 0.09);
}

.source-preview {
  margin-top: 6px;
  color: var(--text-main-2);
  font-size: 12px;
  line-height: 1.55;
  word-break: break-word;
}

.source-meta {
  margin-top: 5px;
  color: var(--text-main-3);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.5;
  word-break: break-word;
}

.evidence-item,
.evidence-empty {
  border: 1px solid var(--ledger-rule);
  border-radius: 6px;
  background: rgba(250, 250, 247, 0.82);
  padding: 10px 11px;
}

.evidence-source {
  color: var(--ledger-ink);
  font-size: 13px;
  font-weight: 800;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confidence-badge {
  color: var(--ledger-gold);
  background: rgba(184, 134, 11, 0.1);
}

.evidence-item p {
  margin: 7px 0;
  color: var(--text-main-2);
  font-size: 12px;
  line-height: 1.6;
}

.evidence-meta,
.report-meta {
  color: var(--text-main-3);
  font-family: var(--font-mono);
  font-size: 11px;
  flex-wrap: wrap;
}

.evidence-empty {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: var(--text-main-2);
  font-size: 12px;
  line-height: 1.6;
}

.evidence-empty svg {
  color: var(--ledger-gold);
  flex-shrink: 0;
  margin-top: 1px;
}

.report-meta {
  margin-top: 10px;
}

@media (max-width: 920px) {
  .trace-grid {
    grid-template-columns: 1fr;
  }

  .trace-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .credible-panel {
    padding: 14px;
  }

  .credible-header {
    flex-direction: column;
    align-items: stretch;
  }

  .trace-status {
    width: fit-content;
  }
}
</style>
