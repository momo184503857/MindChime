<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { get, patch } from '../lib/api';
import { useAction } from '../lib/useData';
const config = ref<any>(null),
  key = ref(''),
  enabled = ref(true),
  error = ref('');
const { busy, run } = useAction();
async function load() {
  try {
    config.value = await get('/research/config');
    enabled.value = config.value.enabled;
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function save() {
  await run(async () => {
    config.value = await patch('/research/config', {
      ...(key.value ? { api_key: key.value } : {}),
      enabled: enabled.value,
    });
    key.value = '';
    error.value = '';
  }, '搜索服务配置已保存');
}
onMounted(load);
</script>
<template>
  <section class="surface panel-pad section-spaced">
    <div class="heading-with-help">
      <h2>思想蒸馏 · 搜索服务</h2>
      <HelpTip label="搜索服务说明">
        使用 Tavily 搜索与正文提取。凭据仅由管理员维护；女娲任务默认关闭联网，开启时才调用此服务。
      </HelpTip>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p class="muted">{{ config?.configured ? '已配置凭据' : '尚未配置凭据' }} · Tavily</p>
    <n-form class="form-grid">
      <n-form-item label="API 密钥">
        <n-input
          v-model:value="key"
          type="password"
          autocomplete="off"
          placeholder="输入新凭据；留空保留原值"
        />
      </n-form-item>
      <n-form-item label="允许联网任务使用"><n-switch v-model:value="enabled" /></n-form-item>
    </n-form>
    <n-button :loading="busy" @click="save">保存搜索配置</n-button>
  </section>
</template>
