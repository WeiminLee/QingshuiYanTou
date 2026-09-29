<template>
  <div class="select-page">
    <el-card>
      <h2>选择身份</h2>
      <p class="hint">请选择本次会话使用的身份</p>
      <div v-if="loading">加载中…</div>
      <div v-else class="user-grid">
        <el-card
          v-for="u in users"
          :key="u.user_id"
          class="user-card"
          shadow="hover"
          @click="pick(u.user_id)"
        >
          <div class="avatar">{{ u.display_name.slice(0, 1) }}</div>
          <div class="name">{{ u.display_name }}</div>
          <div class="uid">@{{ u.user_id }}</div>
        </el-card>
      </div>
      <el-button text class="logout" @click="onLogout">退出登录</el-button>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listUsers, logout, switchUser } from "@/api/account";

const router = useRouter();
const users = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await listUsers();
    users.value = data.users || [];
  } catch (e) {
    if (e?.response?.status === 401) router.push("/login");
  } finally {
    loading.value = false;
  }
});

async function pick(userId) {
  await switchUser(userId);
  router.push("/portfolio");
}

async function onLogout() {
  await logout();
  router.push("/login");
}
</script>

<style scoped>
.select-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.user-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.user-card {
  cursor: pointer;
  text-align: center;
}
.avatar {
  font-size: 28px;
  font-weight: 600;
  color: #409eff;
}
.name {
  margin-top: 8px;
  font-weight: 500;
}
.uid {
  font-size: 12px;
  color: #999;
}
.logout {
  margin-top: 24px;
}
</style>
