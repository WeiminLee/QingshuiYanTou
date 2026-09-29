<template>
  <section
    class="signal-radar"
    :class="{ 'is-paused': paused }"
    @mouseenter="paused = true"
    @mouseleave="paused = false"
  >
    <div class="signal-radar__header">
      <span class="signal-radar__label">预期差信号</span>
      <span class="signal-radar__count">{{ total }}</span>
    </div>
    <div class="signal-radar__filters" aria-label="信号类型筛选">
      <button
        v-for="option in kindOptions"
        :key="option.value"
        class="signal-radar__filter"
        :class="{ 'is-active': activeKind === option.value }"
        type="button"
        :data-testid="`signal-kind-${option.value}`"
        @click="setKind(option.value)"
      >
        {{ option.label }}
      </button>
    </div>

    <div v-if="loading" class="signal-radar__state">加载信号中</div>
    <div v-else-if="error" class="signal-radar__state">{{ error }}</div>
    <div v-else-if="signals.length === 0" class="signal-radar__state">暂无高价值信号</div>

    <div v-else class="signal-radar__viewport">
      <div class="signal-radar__track">
        <div
          v-for="groupIndex in 2"
          :key="groupIndex"
          class="signal-radar__group"
          :aria-hidden="groupIndex === 2"
        >
          <div
            v-for="signal in signals"
            :key="`${groupIndex}-${signal.signal_id}`"
            class="signal-card"
            role="button"
            :tabindex="groupIndex === 1 ? 0 : -1"
            @click="openDetail(signal)"
            @keyup.enter="openDetail(signal)"
          >
            <span class="signal-card__score">{{ signal.value_score }}</span>
            <span class="signal-card__body">
              <span class="signal-card__title">{{ signal.title }}</span>
              <span class="signal-card__summary">{{ signal.summary }}</span>
              <span class="signal-card__meta">
                <span v-if="isCatalyst(signal)" class="signal-card__badge">未来预警</span>
                <span v-if="isCatalyst(signal)"> · {{ leadLabel(signal) }}</span>
                <span v-else>{{ sourceLabel(signal.source_type) }}</span>
                <span v-if="signal.portfolio_hits?.length"> · 持仓 {{ signal.portfolio_hits.length }}</span>
              </span>
            </span>
            <button
              class="signal-card__ask"
              type="button"
              data-testid="ask-signal"
              @click.stop="askSignal(signal)"
            >
              问
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="selectedDetail" class="signal-detail">
      <div class="signal-detail__top">
        <span class="signal-detail__score">{{ selectedDetail.value_score }}</span>
        <button class="signal-detail__close" type="button" @click="selectedDetail = null">收起</button>
      </div>
      <h3>{{ selectedDetail.title }}</h3>
      <p v-if="selectedDetail.evidence_excerpt" class="signal-detail__excerpt">
        {{ selectedDetail.evidence_excerpt }}
      </p>
      <div v-if="isCatalyst(selectedDetail)" class="signal-detail__path">
        {{ catalystDetailLine(selectedDetail) }}
      </div>
      <div v-if="selectedDetail.propagations?.length" class="signal-detail__path">
        {{ selectedDetail.propagations[0].relation_path }}
      </div>
      <p v-if="selectedDetail.propagations?.[0]?.reasoning" class="signal-detail__reasoning">
        {{ selectedDetail.propagations[0].reasoning }}
      </p>
      <button
        class="signal-detail__ask"
        type="button"
        data-testid="ask-signal"
        @click="askSignal(selectedDetail)"
      >
        围绕此信号问 Agent
      </button>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { getSignalDetail, listSignals, updateSignalStatus } from "@/api/signals.js";

const emit = defineEmits(["ask-signal"]);

const signals = ref([]);
const total = ref(0);
const loading = ref(false);
const error = ref("");
const paused = ref(false);
const selectedDetail = ref(null);
const activeKind = ref("all");
const kindOptions = [
  { value: "all", label: "全部" },
  { value: "observed", label: "已发生" },
  { value: "catalyst", label: "未来预警" },
];

const DEFAULT_SIGNAL_QUESTION =
  "请结合我的持仓，分析这个信号的预期差、传导逻辑、可能受益/受损对象和主要风险。";

onMounted(loadSignals);

async function loadSignals() {
  loading.value = true;
  error.value = "";
  try {
    const data = await listSignals(buildListParams());
    signals.value = data.items || [];
    total.value = data.total || signals.value.length;
  } catch {
    error.value = "信号加载失败";
  } finally {
    loading.value = false;
  }
}

function buildListParams() {
  const params = { scope: "all", limit: 8 };
  if (activeKind.value === "observed") {
    params.signal_kind = "observed";
  } else if (activeKind.value === "catalyst") {
    params.signal_kind = "catalyst";
    params.window_days = 5;
  } else {
    params.include_kinds = "observed,catalyst";
  }
  return params;
}

async function setKind(kind) {
  if (activeKind.value === kind) return;
  activeKind.value = kind;
  selectedDetail.value = null;
  await loadSignals();
}

async function openDetail(signal) {
  try {
    selectedDetail.value = await getSignalDetail(signal.signal_id);
    await Promise.resolve(updateSignalStatus(signal.signal_id, "viewed")).catch(() => null);
  } catch {
    selectedDetail.value = { ...signal, propagations: [] };
  }
}

function askSignal(signal) {
  emit("ask-signal", {
    signalId: signal.signal_id,
    question: DEFAULT_SIGNAL_QUESTION,
  });
}

function sourceLabel(sourceType) {
  const labels = {
    announcement: "公告",
    news: "新闻",
    evidence: "证据",
    irm: "互动易",
    research_report: "研报",
    catalyst_event: "未来事件",
  };
  return labels[sourceType] || sourceType || "来源";
}

function isCatalyst(signal) {
  return signal?.signal_kind === "catalyst";
}

function leadLabel(signal) {
  const leadDays = signal?.lead_days ?? signal?.catalyst?.lead_days;
  if (leadDays === 0) return "今日";
  if (leadDays || leadDays === 0) return `${leadDays}天后`;
  return "未来";
}

function catalystDetailLine(signal) {
  const catalyst = signal?.catalyst || {};
  const subjects = Array.isArray(catalyst.subjects) ? catalyst.subjects.join("、") : "";
  const level = catalyst.alert_level || signal?.alert_level || "";
  return [leadLabel(signal), level ? `预警 ${level}` : "", subjects].filter(Boolean).join(" · ");
}
</script>

<style scoped>
.signal-radar {
  padding: 0 16px 10px;
  font-family: var(--ow-font);
}

.signal-radar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 0 4px;
}

.signal-radar__filters {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  margin: 0 0 8px;
  padding: 2px;
  border: 1px solid var(--ow-border);
  border-radius: var(--ow-radius-xs);
  background: var(--ow-bg);
}

.signal-radar__filter {
  min-width: 0;
  height: 24px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--ow-text-3);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}

.signal-radar__filter.is-active {
  background: var(--ow-surface);
  color: var(--ow-text);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

.signal-radar__label {
  color: var(--ow-text-2);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0;
}

.signal-radar__count {
  color: var(--ledger-gold);
  font-size: 12px;
  font-weight: 600;
}

.signal-radar__state,
.signal-radar__viewport {
  border: 1px solid var(--ow-border);
  border-radius: var(--ow-radius-sm);
  background: var(--ow-surface);
}

.signal-radar__state {
  padding: 12px;
  color: var(--ow-text-3);
  font-size: 13.5px;
}

.signal-radar__viewport {
  max-height: 178px;
  overflow: hidden;
}

.signal-radar__track {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  animation: signal-scroll 28s linear infinite;
}

.signal-radar__group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.signal-radar.is-paused .signal-radar__track {
  animation-play-state: paused;
}

.signal-card {
  position: relative;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 8px;
  width: 100%;
  padding: 9px;
  border: 1px solid var(--ow-border);
  border-left: 3px solid rgba(184, 134, 11, 0.78);
  border-radius: var(--ow-radius-xs);
  background: var(--ow-bg);
  color: var(--ow-text-2);
  text-align: left;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
  transition:
    background 0.15s,
    border-color 0.15s,
    box-shadow 0.15s,
    transform 0.15s;
}

.signal-card:hover {
  background: #fcfcfd;
  border-color: var(--ow-border-strong);
  color: var(--ow-text);
  box-shadow: 0 5px 16px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.signal-card__score {
  color: var(--ledger-gold);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.1;
}

.signal-card__body {
  min-width: 0;
}

.signal-card__title,
.signal-card__summary,
.signal-card__meta {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.signal-card__title {
  color: var(--ow-text);
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.35;
}

.signal-card__summary {
  margin-top: 3px;
  color: var(--ow-text-2);
  font-size: 12px;
  line-height: 1.45;
}

.signal-card__meta {
  margin-top: 4px;
  color: var(--ow-text-3);
  font-size: 11.5px;
}

.signal-card__badge {
  color: #a15c07;
  font-weight: 600;
}

.signal-card__ask {
  position: absolute;
  right: 6px;
  top: 6px;
  display: none;
  height: 22px;
  min-width: 26px;
  border: 1px solid var(--ow-border-strong);
  border-radius: 7px;
  background: var(--ow-bg);
  color: var(--ow-text-2);
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.signal-card:hover .signal-card__ask {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.signal-detail {
  margin-top: 8px;
  padding: 12px;
  border: 1px solid var(--ow-border);
  border-radius: var(--ow-radius-sm);
  background: var(--ow-bg);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}

.signal-detail__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.signal-detail__score {
  color: var(--ledger-gold);
  font-size: 16px;
  font-weight: 700;
}

.signal-detail__close {
  border: 0;
  background: transparent;
  color: var(--ow-text-3);
  cursor: pointer;
  font-size: 11px;
}

.signal-detail h3 {
  margin: 6px 0;
  color: var(--ow-text);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.45;
}

.signal-detail__excerpt,
.signal-detail__reasoning,
.signal-detail__path {
  margin: 6px 0 0;
  color: var(--ow-text-2);
  font-size: 13px;
  line-height: 1.55;
}

.signal-detail__path {
  color: var(--ow-accent);
}

.signal-detail__ask {
  width: 100%;
  height: 30px;
  margin-top: 9px;
  border: 1px solid var(--ow-border-strong);
  border-radius: var(--ow-radius-xs);
  background: var(--ow-surface);
  color: var(--ow-text);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
}

.signal-detail__ask:hover {
  background: var(--ow-hover);
}

@keyframes signal-scroll {
  0% {
    transform: translateY(0);
  }
  100% {
    transform: translateY(calc(-50% - 3px));
  }
}
</style>
