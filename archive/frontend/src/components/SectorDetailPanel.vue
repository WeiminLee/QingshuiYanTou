<template>
  <div v-if="sector" class="sector-detail-panel">
    <div class="detail-header">
      <div class="sector-name">{{ sector.name || sector.ts_code }}</div>
      <div :class="['sector-pct', pctClass(sector.pct_change)]">
        {{ pctSign(sector.pct_change) }}{{ sector.pct_change?.toFixed(2) }}%
      </div>
    </div>

    <div class="metrics-row">
      <div class="metric-item">
        <div class="metric-label">成交额</div>
        <div class="metric-value">{{ formatAmount(sector.amount) }}</div>
      </div>
    </div>

    <div v-if="sector.constituents?.length" class="constituent-chart">
      <div ref="chartRef" class="mini-chart" />
    </div>

    <div v-if="sector.constituents?.length" class="constituent-list">
      <div class="constituent-title">成分股 Top10</div>
      <div v-for="c in sector.constituents.slice(0, 10)" :key="c.ts_code" class="constituent-row">
        <span class="c-name">{{ c.name || c.ts_code }}</span>
        <span :class="['c-pct', pctClass(c.pct_change)]">
          {{ pctSign(c.pct_change) }}{{ c.pct_change?.toFixed(2) }}%
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from "vue";
import { storeToRefs } from "pinia";
import { useUiStore } from "../store/ui.js";
import { useEChart } from "../composables/useEChart.js";

const uiStore = useUiStore();
const { selectedTarget } = storeToRefs(uiStore);

const chartRef = ref(null);
const { initChart, disposeChart } = useEChart(chartRef);

const sector = computed(() =>
  selectedTarget.value?.type === "sector" ? selectedTarget.value.data : null,
);

function formatAmount(val) {
  if (!val) return "-";
  if (val >= 1e8) return (val / 1e8).toFixed(2) + "亿";
  if (val >= 1e4) return (val / 1e4).toFixed(2) + "万";
  return String(val);
}

function pctClass(val) {
  if (!val) return "neutral-text";
  if (val > 0) return "gain-text";
  if (val < 0) return "loss-text";
  return "neutral-text";
}

function pctSign(val) {
  if (!val) return "";
  return val >= 0 ? "+" : "";
}

function renderChart() {
  if (!chartRef.value || !sector.value?.constituents?.length) return;
  const top = sector.value.constituents.slice(0, 10);
  const names = top.map((c) => (c.name || c.ts_code || "").slice(0, 6));
  const pcts = top.map((c) => c.pct_change ?? 0);
  const colors = pcts.map((p) => (p >= 0 ? "#ef4444" : "#22c55e"));

  const inst = initChart();
  inst.setOption({
    title: {
      text: "成分股涨跌幅 Top10",
      left: 0,
      textStyle: { fontSize: 12, fontWeight: 600, color: "#303133" },
    },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: names, axisLabel: { fontSize: 10, color: "#909399" } },
    yAxis: { type: "value", axisLabel: { formatter: "{value}%", fontSize: 10 } },
    series: [
      {
        type: "bar",
        data: pcts.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
        barWidth: "60%",
      },
    ],
  });
}

watch(sector, async () => {
  await nextTick();
  renderChart();
});
onMounted(async () => {
  await nextTick();
  renderChart();
});
onBeforeUnmount(disposeChart);
</script>

<style scoped>
.sector-detail-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sector-name {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}
.sector-pct {
  font-size: 22px;
  font-weight: 600;
}

.gain-text {
  color: #ef4444;
}
.loss-text {
  color: #22c55e;
}
.neutral-text {
  color: #909399;
}

.metrics-row {
  display: flex;
  gap: 16px;
}
.metric-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.metric-label {
  font-size: 12px;
  color: #909399;
}
.metric-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.constituent-chart {
  width: 100%;
}
.mini-chart {
  width: 100%;
  height: 120px;
}

.constituent-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
}
.constituent-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.constituent-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
.c-name {
  color: #303133;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.c-pct {
  font-weight: 600;
  flex-shrink: 0;
}
</style>
