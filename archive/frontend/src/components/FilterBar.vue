<template>
  <div class="filter-bar">
    <!-- Source type filters -->
    <div class="filter-group">
      <span class="filter-label">来源：</span>
      <el-check-tag
        v-for="src in sourceOptions"
        :key="src.key"
        :checked="activeSources.includes(src.key)"
        class="filter-tag"
        @change="toggleSource(src.key)"
      >
        <span class="source-badge" :style="{ background: src.bg, color: src.color }">
          {{ src.label }}
        </span>
      </el-check-tag>
    </div>

    <!-- Confidence tier filters -->
    <div class="filter-group">
      <span class="filter-label">置信度：</span>
      <el-check-tag
        v-for="tier in tierOptions"
        :key="tier.value"
        :checked="activeTiers.includes(tier.value)"
        class="filter-tag"
        @change="toggleTier(tier.value)"
      >
        <span class="tier-badge" :style="{ background: tier.bg, color: tier.color }">
          {{ tier.label }}
        </span>
      </el-check-tag>
    </div>

    <!-- Clear all -->
    <el-button v-if="hasActiveFilters" size="small" link @click="clearAll"> 清除筛选 </el-button>
  </div>
</template>

<script setup>
import { ref, computed } from "vue";

const emit = defineEmits(["change"]);

const activeSources = ref([]);
const activeTiers = ref([]);

const sourceOptions = [
  { key: "cls", label: "财联社", color: "#ff6b35", bg: "#fff4ef" },
  { key: "announcement", label: "公告", color: "#7c3aed", bg: "#f5f3ff" },
  { key: "research", label: "研报", color: "#0891b2", bg: "#ecfeff" },
  { key: "qa", label: "互动易", color: "#059669", bg: "#ecfdf5" },
];

const tierOptions = [
  { value: 0, label: "TIER0", color: "#059669", bg: "#ecfdf5" },
  { value: 1, label: "TIER1", color: "#16a34a", bg: "#f0fdf4" },
  { value: 2, label: "TIER2", color: "#ca8a04", bg: "#fefce8" },
  { value: 3, label: "TIER3", color: "#ea580c", bg: "#fff7ed" },
  { value: 4, label: "TIER4", color: "#dc2626", bg: "#fef2f2" },
];

const hasActiveFilters = computed(
  () => activeSources.value.length > 0 || activeTiers.value.length > 0,
);

function toggleSource(key) {
  const idx = activeSources.value.indexOf(key);
  if (idx >= 0) activeSources.value.splice(idx, 1);
  else activeSources.value.push(key);
  emitChange();
}

function toggleTier(val) {
  const idx = activeTiers.value.indexOf(val);
  if (idx >= 0) activeTiers.value.splice(idx, 1);
  else activeTiers.value.push(val);
  emitChange();
}

function clearAll() {
  activeSources.value = [];
  activeTiers.value = [];
  emitChange();
}

function emitChange() {
  emit("change", {
    sources: [...activeSources.value],
    tiers: [...activeTiers.value],
  });
}
</script>

<style scoped>
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 4px;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-label {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}

.filter-tag {
  margin: 0;
}

.source-badge,
.tier-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}
</style>
