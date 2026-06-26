<template>
  <div class="portfolio-page">
    <el-card>
      <div class="header">
        <h2>我的持仓</h2>
        <div class="header-right">
          <span class="user-tag">@{{ currentUserId }}</span>
          <el-button text @click="goSwitch">切换身份</el-button>
          <el-button text @click="onLogout">退出</el-button>
        </div>
      </div>

      <el-autocomplete
        v-model="searchText"
        :fetch-suggestions="onSearch"
        placeholder="搜索股票代码或名称"
        :trigger-on-focus="true"
        :debounce="300"
        clearable
        class="search"
        data-testid="stock-search"
        @select="onSelect"
      >
        <template #default="{ item }">
          <div class="search-item">
            <span class="ts">{{ item.ts_code }}</span>
            <span class="name">{{ item.name }}</span>
            <span class="ind">{{ item.industry || "" }}</span>
          </div>
        </template>
      </el-autocomplete>
      <el-button
        type="primary"
        :disabled="!pendingAdd"
        data-testid="add-button"
        @click="confirmAdd"
      >
        加入持仓
      </el-button>

      <el-divider />

      <el-table v-loading="loading" :data="positions" empty-text="还没有持仓，搜索添加第一只">
        <el-table-column prop="ts_code" label="代码" width="120" />
        <el-table-column prop="stock_name" label="名称" />
        <el-table-column prop="created_at" label="加入时间" width="200">
          <template #default="{ row }">
            {{ new Date(row.created_at).toLocaleString() }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="right">
          <template #default="{ row }">
            <el-button type="danger" text data-testid="remove-button" @click="confirmRemove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  addPortfolio,
  listPortfolio,
  logout,
  removePortfolio,
  searchStocks,
  whoami,
} from "@/api/account";

const router = useRouter();
const positions = ref([]);
const loading = ref(false);
const searchText = ref("");
const pendingAdd = ref(null);
const currentUserId = ref("");

async function refreshUser() {
  const me = await whoami();
  currentUserId.value = me.user?.user_id || "";
  if (!currentUserId.value) {
    router.push("/select-identity");
  }
}

async function refresh() {
  loading.value = true;
  try {
    const data = await listPortfolio();
    positions.value = data.positions || [];
  } finally {
    loading.value = false;
  }
}

async function onSearch(queryString, cb) {
  try {
    const data = await searchStocks(queryString || "", 10);
    const items = (data.items || []).map((i) => ({
      value: `${i.ts_code} ${i.name}`,
      ...i,
    }));
    cb(items);
  } catch {
    cb([]);
  }
}

function onSelect(item) {
  pendingAdd.value = item;
  searchText.value = `${item.ts_code} ${item.name}`;
}

async function confirmAdd() {
  if (!pendingAdd.value) return;
  try {
    await addPortfolio(pendingAdd.value.ts_code);
    ElMessage.success(`已加入 ${pendingAdd.value.name}`);
    pendingAdd.value = null;
    searchText.value = "";
    await refresh();
  } catch (e) {
    const code = e?.response?.status;
    if (code === 409) ElMessage.warning("已在持仓中");
    else if (code === 422) ElMessage.error("股票代码无效");
    else ElMessage.error("添加失败");
  }
}

async function confirmRemove(row) {
  try {
    await ElMessageBox.confirm(`确定删除 ${row.stock_name}?`, "提示", { type: "warning" });
    await removePortfolio(row.ts_code);
    ElMessage.success("已删除");
    await refresh();
  } catch (e) {
    if (e === "cancel") return;
    ElMessage.error("删除失败");
  }
}

function goSwitch() {
  router.push("/select-identity");
}

async function onLogout() {
  await logout();
  router.push("/login");
}

onMounted(async () => {
  await refreshUser();
  await refresh();
});

function onUnauthorized() {
  router.push("/login");
}
window.addEventListener("account:unauthorized", onUnauthorized);
onUnmounted(() => {
  window.removeEventListener("account:unauthorized", onUnauthorized);
});
</script>

<style scoped>
.portfolio-page {
  padding: 24px;
  min-height: 100vh;
  background: #f5f7fa;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-right {
  display: flex;
  gap: 12px;
  align-items: center;
}
.user-tag {
  color: #999;
  font-size: 13px;
}
.search {
  width: 320px;
  margin-right: 8px;
}
.search-item {
  display: flex;
  gap: 12px;
  font-size: 13px;
}
.search-item .ts {
  font-weight: 600;
  color: #409eff;
}
.search-item .ind {
  color: #999;
  margin-left: auto;
}
</style>
