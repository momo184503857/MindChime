<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { signIn, isAdmin } from '../lib/auth';
import { useAppStore } from '../stores/app';
const route = useRoute(),
  router = useRouter(),
  app = useAppStore();
const username = ref(''),
  password = ref(''),
  busy = ref(false),
  error = ref('');
async function submit() {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    await signIn(username.value.trim(), password.value);
    const target = String(route.query.next || '');
    await router.replace(
      target.startsWith('/') &&
        !target.startsWith('//') &&
        !target.startsWith('/login') &&
        (isAdmin.value || !target.startsWith('/admin'))
        ? target
        : isAdmin.value
          ? '/admin'
          : '/',
    );
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="login-page">
    <section class="login-card surface">
      <div class="eyebrow">MINDCHIME · 思鸣</div>
      <h1>让知识，进入下一次思考。</h1>
      <p class="muted">登录你的本地工作区。</p>
      <form @submit.prevent="submit">
        <label for="username">账号</label>
        <n-input
          id="username"
          v-model:value="username"
          autocomplete="username"
          placeholder="输入账号"
          :input-props="{ 'aria-label': '账号' }"
        />
        <label for="password">密码</label>
        <n-input
          id="password"
          v-model:value="password"
          type="password"
          autocomplete="current-password"
          show-password-on="click"
          placeholder="输入密码"
          :input-props="{ 'aria-label': '密码' }"
        />
        <p v-if="error" role="alert" class="error-text">{{ error }}</p>
        <n-button
          attr-type="submit"
          type="primary"
          :loading="busy"
          :disabled="!username.trim() || !password"
          block
        >
          登录
        </n-button>
      </form>
      <div class="login-footer">
        <span class="muted small">本地测试版</span>
        <n-button text @click="app.toggleTheme">{{ app.dark ? '浅色主题' : '深色主题' }}</n-button>
      </div>
    </section>
  </main>
</template>
<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--bg);
}
.login-card {
  width: min(100%, 460px);
  padding: 40px;
}
h1 {
  font-size: 26px;
  margin: 20px 0 12px;
  line-height: 1.5;
}
form {
  display: grid;
  gap: 12px;
  margin-top: 32px;
}
form > .n-button {
  margin-top: 16px;
}
label {
  margin-top: 8px;
  font-weight: 500;
}
.login-footer {
  margin-top: 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.error-text {
  color: var(--danger, #b33939);
}
</style>
