<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2>清水投研 · 登录</h2>
      <p class="hint">输入主密码以访问个人化功能</p>
      <el-form @submit.prevent="onSubmit">
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="主密码"
            show-password
            autofocus
            data-testid="password-input"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" data-testid="login-button" @click="onSubmit">
          登录
        </el-button>
        <p v-if="error" class="error" data-testid="error-text">{{ error }}</p>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import { login } from "@/api/account";

const router = useRouter();
const password = ref("");
const loading = ref(false);
const error = ref("");

async function onSubmit() {
  if (!password.value) {
    error.value = "请输入主密码";
    return;
  }
  error.value = "";
  loading.value = true;
  try {
    const data = await login(password.value);
    if (data.users && data.users.length === 1) {
      const { switchUser } = await import("@/api/account");
      await switchUser(data.users[0].user_id);
      router.push("/portfolio");
    } else {
      router.push("/select-identity");
    }
  } catch (e) {
    error.value = e?.response?.data?.detail || "登录失败";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.login-card {
  width: 360px;
}
.hint {
  color: #999;
  font-size: 13px;
  margin-bottom: 16px;
}
.error {
  color: #f56c6c;
  margin-top: 12px;
  font-size: 13px;
}
</style>
