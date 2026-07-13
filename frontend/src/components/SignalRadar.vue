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

    <div v-if="loading" class="signal-radar__state">加载信号中</div>
    <div v-else-if="error" class="signal-radar__state">{{ error }}</div>
    <div v-else-if="signals.length === 0" class="signal-radar__state">暂无高价值信号</div>

    <div v-else class="signal-radar__viewport">
      <div class="signal-radar__track">
        <div
          v-for="signal in signals"
          :key="signal.signal_id"
          class="signal-card"
          role="button"
          tabindex="0"
          @click="openDetail(signal)"
          @keyup.enter="openDetail(signal)"
        >
          <span class="signal-card__score">{{ signal.value_score }}</span>
          <span class="signal-card__body">
            <span class="signal-card__title">{{ signal.title }}</span>
            <span class="signal-card__summary">{{ signal.summary }}</span>
            <span class="signal-card__meta">
              {{ sourceLabel(signal.source_type) }}
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

    <div v-if="selectedDetail" class="signal-detail">
      <div class="signal-detail__top">
        <span class="signal-detail__score">{{ selectedDetail.value_score }}</span>
        <button class="signal-detail__close" type="button" @click="selectedDetail = null">收起</button>
      </div>
      <h3>{{ selectedDetail.title }}</h3>
      <p v-if="selectedDetail.evidence_excerpt" class="signal-detail__excerpt">
        {{ selectedDetail.evidence_excerpt }}
      </p>
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

const DEFAULT_SIGNAL_QUESTION =
  "请结合我的持仓，分析这个信号的预期差、传导逻辑、可能受益/受损对象和主要风险。";

onMounted(loadSignals);

async function loadSignals() {
  loading.value = true;
  error.value = "";
  try {
    const data = await listSignals({ scope: "all", limit: 8 });
    signals.value = data.items || [];
    total.value = data.total || signals.value.length;
  } catch {
    error.value = "信号加载失败";
  } finally {
    loading.value = false;
  }
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
  };
  return labels[sourceType] || sourceType || "来源";
}
</script>

<style scoped>
.signal-radar {
  padding: 0 16px 10px;
}

.signal-radar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 0 4px;
}

.signal-radar__label {
  color: var(--text-sidebar-muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
}

.signal-radar__count {
  color: var(--ledger-gold);
  font-size: 10px;
}

.signal-radar__state,
.signal-radar__viewport {
  border: 1px solid rgba(184, 134, 11, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.035);
}

.signal-radar__state {
  padding: 12px;
  color: var(--text-sidebar-muted);
  font-size: 11px;
}

.signal-radar__viewport {
  max-height: 178px;
  overflow: hidden;
}

.signal-radar__track {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 7px;
  animation: signal-scroll 18s linear infinite;
}

.signal-radar.is-paused .signal-radar__track {
  animation-play-state: paused;
}

.signal-card {
  position: relative;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 7px;
  width: 100%;
  padding: 8px;
  border: 1px solid rgba(184, 134, 11, 0.16);
  border-left: 3px solid var(--ledger-gold);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-sidebar);
  text-align: left;
  cursor: pointer;
}

.signal-card:hover {
  background: var(--ledger-spine-3);
  color: var(--text-sidebar-hi);
}

.signal-card__score {
  color: var(--ledger-gold);
  font-size: 15px;
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
  color: var(--text-sidebar-hi);
  font-size: 12px;
  line-height: 1.3;
}

.signal-card__summary {
  margin-top: 3px;
  color: var(--text-sidebar-muted);
  font-size: 10px;
  line-height: 1.35;
}

.signal-card__meta {
  margin-top: 4px;
  color: var(--ledger-gold);
  font-size: 10px;
}

.signal-card__ask {
  position: absolute;
  right: 6px;
  top: 6px;
  display: none;
  height: 22px;
  min-width: 26px;
  border: 1px solid rgba(232, 163, 23, 0.45);
  border-radius: 5px;
  background: #2c2419;
  color: var(--ledger-gold);
  font-size: 11px;
  cursor: pointer;
}

.signal-card:hover .signal-card__ask {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.signal-detail {
  margin-top: 8px;
  padding: 10px;
  border: 1px solid rgba(184, 134, 11, 0.2);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.055);
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
  color: var(--text-sidebar-muted);
  cursor: pointer;
  font-size: 11px;
}

.signal-detail h3 {
  margin: 6px 0;
  color: var(--text-sidebar-hi);
  font-size: 12px;
  line-height: 1.45;
}

.signal-detail__excerpt,
.signal-detail__reasoning,
.signal-detail__path {
  margin: 6px 0 0;
  color: var(--text-sidebar);
  font-size: 11px;
  line-height: 1.55;
}

.signal-detail__path {
  color: var(--ledger-gold);
}

.signal-detail__ask {
  width: 100%;
  height: 30px;
  margin-top: 9px;
  border: 1px solid rgba(184, 134, 11, 0.35);
  border-radius: 6px;
  background: rgba(184, 134, 11, 0.14);
  color: var(--ledger-gold);
  cursor: pointer;
  font-size: 12px;
}

@keyframes signal-scroll {
  0% {
    transform: translateY(0);
  }
  100% {
    transform: translateY(-32px);
  }
}
</style>
