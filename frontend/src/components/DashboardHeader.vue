<template>
  <div class="dashboard-header">
    <span class="dashboard-title">投研看板</span>
    <div class="header-actions">
      <el-button
        :icon="collapsed ? Expand : Fold"
        text
        @click="$emit('toggle-sidebar')"
      />
    </div>
  </div>
</template>

<script setup>
import { Fold, Expand } from '@element-plus/icons-vue'

defineProps({
  collapsed: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['toggle-sidebar'])
</script>

<style scoped>
.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 20px;
  background: #1a1a2e;
  color: #fff;
  flex-shrink: 0;
}

.dashboard-title {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
}

.header-actions {
  display: flex;
  align-items: center;
}

.header-actions .el-button {
  color: rgba(255, 255, 255, 0.7);
  font-size: 18px;
}

.header-actions .el-button:hover {
  color: #fff;
}
</style>
