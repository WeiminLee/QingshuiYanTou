<template>
  <div class="stock-detail">
    <!-- 股票基本信息 + 评分概览 -->
    <el-card class="info-card">
      <div class="stock-info">
        <div class="info-left">
          <h2>{{ stockInfo.name }} ({{ stockInfo.ts_code }})</h2>
          <p class="industry">{{ stockInfo.industry }}</p>
        </div>
        <div class="info-right">
          <div class="price-info">
            <span class="current-price">{{ currentPrice.toFixed(2) }}</span>
            <span :class="['pct-change', pctChange >= 0 ? 'up' : 'down']">
              {{ pctChange >= 0 ? "+" : "" }}{{ pctChange.toFixed(2) }}%
            </span>
          </div>
          <div v-if="stockScore" class="score-badge">
            <el-tag :type="scoreTagType" size="small"
              >综合评分 {{ stockScore.total_score.toFixed(1) }}</el-tag
            >
          </div>
        </div>
      </div>

      <!-- 评分 breakdown -->
      <div v-if="stockScore" class="score-breakdown">
        <el-tag size="small" type="info"
          >动量 {{ stockScore.breakdown.momentum_score.toFixed(0) }}</el-tag
        >
        <el-tag size="small" type="info"
          >趋势 {{ stockScore.breakdown.trend_score.toFixed(0) }}</el-tag
        >
        <el-tag size="small" type="info"
          >资金 {{ stockScore.breakdown.capital_score.toFixed(0) }}</el-tag
        >
        <el-tag size="small" type="info"
          >概念 {{ stockScore.breakdown.concept_bonus.toFixed(1) }}</el-tag
        >
        <el-tag size="small" type="info"
          >估值 {{ stockScore.breakdown.valuation_bonus.toFixed(0) }}</el-tag
        >
      </div>
      <div style="margin-top: 12px; text-align: right">
        <el-button type="primary" size="small" @click="$router.push('/report')">投研分析</el-button>
      </div>
    </el-card>

    <!-- 概念评分 & K线图 row -->
    <el-row :gutter="12" style="margin-bottom: 12px">
      <!-- 所属概念评分 -->
      <el-col :span="6">
        <el-card class="concept-card">
          <template #header>
            <div class="card-header">所属概念评分</div>
          </template>
          <div v-if="stockScore?.concept_scores?.length" class="concept-list">
            <div
              v-for="c in stockScore.concept_scores.slice(0, 8)"
              :key="c.concept_ts_code"
              class="concept-item"
            >
              <span class="concept-name">{{ c.name }}</span>
              <span :class="['score-num', getScoreClass(c.score)]">{{ c.score.toFixed(1) }}</span>
            </div>
          </div>
          <el-empty v-else description="暂无概念评分数据" :image-size="60" />
        </el-card>
      </el-col>

      <!-- K线图 -->
      <el-col :span="18">
        <el-card class="chart-card">
          <template #header>
            <div class="card-header">
              <span>K线走势</span>
            </div>
          </template>
          <div ref="chartRef" class="kline-chart" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 互动易Q&A + 公告 row -->
    <el-row :gutter="12">
      <!-- 互动易Q&A -->
      <el-col :span="12">
        <el-card class="qa-card">
          <template #header>
            <div class="card-header">
              <span>互动易 Q&A</span>
              <el-button size="small" @click="fetchQA">刷新</el-button>
            </div>
          </template>
          <div v-if="qaLoading" style="text-align: center; padding: 40px">
            <el-icon class="is-loading"><Loading /></el-icon>
          </div>
          <el-timeline v-else-if="qaItems.length > 0" size="small">
            <el-timeline-item
              v-for="(item, idx) in qaItems"
              :key="idx"
              :timestamp="item.a_time || item.q_time || item.ann_date"
              placement="top"
            >
              <div class="qa-item">
                <div class="qa-q">
                  <el-tag size="small" type="info" style="margin-right: 4px">问</el-tag>
                  <span>{{ item.question }}</span>
                </div>
                <div v-if="item.answer" class="qa-a">
                  <el-tag size="small" type="success" style="margin-right: 4px">答</el-tag>
                  <span class="answer-text">{{ item.answer }}</span>
                </div>
                <div v-if="item.signals?.length" class="qa-signals">
                  <el-tag
                    v-for="sig in item.signals"
                    :key="sig"
                    size="small"
                    type="warning"
                    style="margin-right: 4px"
                    >{{ sig }}</el-tag
                  >
                </div>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无Q&A数据" :image-size="60" />
        </el-card>
      </el-col>

      <!-- 公告列表 -->
      <el-col :span="12">
        <el-card class="ann-card">
          <template #header>
            <div class="card-header">
              <span>公司公告</span>
              <el-button size="small" @click="fetchAnnouncements">刷新</el-button>
            </div>
          </template>
          <el-table
            v-if="annItems.length > 0"
            :data="annItems"
            size="small"
            max-height="400"
            style="font-size: 13px"
          >
            <el-table-column prop="ann_date" label="日期" width="90" />
            <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
            <el-table-column prop="type" label="类型" width="80" />
          </el-table>
          <el-empty v-else description="暂无公告" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import { Loading } from "@element-plus/icons-vue";
import * as echarts from "echarts";
import axios from "axios";

const route = useRoute();
const tsCode = ref(route.params.tsCode || route.params.ts_code);

const stockInfo = ref({ ts_code: tsCode.value, name: "", industry: "" });
const dailyData = ref([]);
const currentPrice = ref(0);
const pctChange = ref(0);
const chartRef = ref(null);
let chart = null;

// 个股评分
const stockScore = ref(null);

// 互动易 Q&A
const qaItems = ref([]);
const qaLoading = ref(false);

// 公告
const annItems = ref([]);

// ── 基本信息 ──────────────────────────────────────
const fetchStockInfo = async () => {
  try {
    const res = await axios.get(`/api/v1/stocks/${tsCode.value}`);
    stockInfo.value = res.data;
  } catch (e) {
    console.error("获取股票信息失败", e);
  }
};

// ── 个股评分 ─────────────────────────────────────
const fetchStockScore = async () => {
  try {
    const res = await axios.get(`/api/v1/concept/scores/stocks/${tsCode.value}`);
    stockScore.value = res.data;
  } catch (e) {
    console.error("获取个股评分失败", e);
  }
};

const scoreTagType = computed(() => {
  if (!stockScore.value) return "info";
  const s = stockScore.value.total_score;
  if (s >= 70) return "success";
  if (s >= 40) return "warning";
  return "danger";
});

const getScoreClass = (score) => {
  if (score >= 80) return "score-high";
  if (score >= 60) return "score-mid";
  return "score-low";
};

// ── 日线数据 ──────────────────────────────────────
const fetchDailyData = async () => {
  try {
    const res = await axios.get(`/api/v1/data/daily/${tsCode.value}`, { params: { limit: 120 } });
    dailyData.value = res.data.items || [];
    if (dailyData.value.length > 0) {
      const latest = dailyData.value[dailyData.value.length - 1];
      currentPrice.value = latest.close || 0;
      pctChange.value = latest.pct_chg || 0;
    }
    renderChart();
  } catch (e) {
    console.error("获取日线数据失败", e);
  }
};

// ── K线图 ────────────────────────────────────────
const renderChart = () => {
  if (!chartRef.value || dailyData.value.length === 0) return;
  if (!chart) {
    chart = echarts.init(chartRef.value);
  }
  const dates = dailyData.value.map((d) => d.trade_date);
  const ohlc = dailyData.value.map((d) => [d.open, d.close, d.low, d.high]);
  const volumes = dailyData.value.map((d) => d.vol);

  chart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    grid: [
      { left: "8%", right: "5%", top: "10%", height: "55%" },
      { left: "8%", right: "5%", top: "75%", height: "15%" },
    ],
    xAxis: [
      { type: "category", data: dates, boundaryGap: true },
      { type: "category", gridIndex: 1, data: dates, boundaryGap: true },
    ],
    yAxis: [{ scale: true }, { scale: true, gridIndex: 1, splitNumber: 2 }],
    dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: 60, end: 100 }],
    series: [
      {
        type: "candlestick",
        data: ohlc,
        itemStyle: {
          color: "#ef232a",
          color0: "#14b143",
          borderColor: "#ef232a",
          borderColor0: "#14b143",
        },
      },
      {
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: { color: "#7f9" },
      },
    ],
  });
};

// ── 互动易 Q&A ──────────────────────────────────
const fetchQA = async () => {
  qaLoading.value = true;
  try {
    const res = await axios.get(`/api/v1/information/qa/${tsCode.value}`, {
      params: { limit: 10 },
    });
    qaItems.value = res.data.items || [];
  } catch (e) {
    console.error("获取Q&A失败", e);
  } finally {
    qaLoading.value = false;
  }
};

// ── 公告列表 ──────────────────────────────────────
const fetchAnnouncements = async () => {
  try {
    const res = await axios.get(`/api/v1/information/announcements/${tsCode.value}`, {
      params: { limit: 20 },
    });
    annItems.value = (res.data.items || []).map((a) => ({
      ann_date: a.ann_date || "",
      title: a.title || "",
      type: a.type || "",
    }));
  } catch (e) {
    console.error("获取公告失败", e);
  }
};

onMounted(() => {
  fetchStockInfo();
  fetchStockScore();
  fetchDailyData();
  fetchQA();
  fetchAnnouncements();
});

onUnmounted(() => {
  if (chart) chart.dispose();
});
</script>

<style scoped>
.stock-detail {
  max-width: 1400px;
  margin: 0 auto;
}

.info-card {
  margin-bottom: 12px;
}

.stock-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.info-left h2 {
  margin: 0;
  font-size: 20px;
}
.info-left .industry {
  margin: 4px 0 0;
  color: #909399;
}

.price-info {
  text-align: right;
}
.current-price {
  font-size: 28px;
  font-weight: bold;
  margin-right: 10px;
}
.pct-change {
  font-size: 16px;
  font-weight: 500;
}
.pct-change.up {
  color: #f56c6c;
}
.pct-change.down {
  color: #67c23a;
}
.score-badge {
  margin-top: 4px;
  text-align: right;
}

.score-breakdown {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.kline-chart {
  height: 360px;
}

/* 概念评分 */
.concept-list {
  font-size: 13px;
}
.concept-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  border-bottom: 1px solid #f0f0f0;
}
.concept-item:last-child {
  border-bottom: none;
}
.concept-name {
  color: #606266;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.score-num {
  font-weight: 600;
  min-width: 36px;
  text-align: right;
}
.score-num.score-high {
  color: #67c23a;
}
.score-num.score-mid {
  color: #e6a23c;
}
.score-num.score-low {
  color: #909399;
}

/* Q&A */
.qa-item {
  font-size: 13px;
}
.qa-q {
  color: #303133;
  margin-bottom: 4px;
}
.qa-a {
  color: #606266;
  margin-bottom: 4px;
}
.answer-text {
  font-size: 12px;
}
.qa-signals {
  margin-top: 4px;
}
</style>
