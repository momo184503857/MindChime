<script setup lang="ts">
defineProps<{
  loading?: boolean;
  error?: string;
  empty?: boolean;
  title?: string;
  description?: string;
}>();
defineEmits(['retry']);
</script>
<template>
  <div v-if="loading" class="loading-state" role="status" aria-label="正在加载">
    <n-skeleton height="32px" width="40%" />
    <n-skeleton v-for="n in 3" :key="n" height="68px" style="margin-top: 16px" />
  </div>
  <div v-else-if="error" class="state-panel" role="alert">
    <n-alert type="error" title="暂时无法加载">{{ error }}</n-alert>
    <n-button @click="$emit('retry')" style="margin-top: 16px">重试</n-button>
  </div>
  <div v-else-if="empty" class="empty-state">
    <slot name="icon" />
    <h2>{{ title || '还没有内容' }}</h2>
    <p>{{ description || '从一个小小的开始，建立你的知识工作区。' }}</p>
    <slot name="action" />
  </div>
  <slot v-else />
</template>
