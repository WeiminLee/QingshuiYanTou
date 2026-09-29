<template>
  <div class="data-panel">
    <!-- Loading state -->
    <div v-if="loading" class="panel-loading">
      <el-skeleton :rows="6" animated />
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="panel-error">
      <el-result icon="error" title="加载失败" :sub-title="error">
        <template #extra>
          <el-button type="primary" @click="$emit('retry')"> 重新加载 </el-button>
        </template>
      </el-result>
    </div>

    <!-- Empty state -->
    <div v-else-if="isEmpty" class="panel-empty">
      <el-empty description="暂无数据" />
    </div>

    <!-- Data present -->
    <div v-else class="panel-content">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: [String, null],
    default: null,
  },
  data: {
    type: [Array, Object, null],
    default: null,
  },
});

defineEmits(["retry"]);

// isEmpty = true only when data is an empty array (null/undefined means "not yet loaded")
const isEmpty = computed(() => {
  if (props.data === null || props.data === undefined) return false;
  if (Array.isArray(props.data)) return props.data.length === 0;
  return false;
});
</script>

<style scoped>
.data-panel {
  width: 100%;
  min-height: 200px;
}

.panel-loading,
.panel-error,
.panel-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  padding: 24px;
}

.panel-content {
  width: 100%;
}
</style>
