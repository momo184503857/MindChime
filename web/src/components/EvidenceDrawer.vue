<script setup lang="ts">
import { ref, watch } from 'vue';
import { get } from '../lib/api';
import { type Reference, textOf, locationLabel } from '../lib/types';
import ResourceState from './ResourceState.vue';
const props = defineProps<{ reference: Reference | null; show: boolean }>();
const emit = defineEmits(['update:show']);
const loading = ref(false);
const error = ref('');
const data = ref<any>(null);
async function loadEvidence() {
  if (!props.show || !props.reference) return;
  loading.value = true;
  error.value = '';
  try {
    const params = new URLSearchParams();
    Object.entries(props.reference).forEach(([k, v]) => {
      if (
        v != null &&
        ['source_id', 'source_version', 'chapter_id', 'chapter_version', 'start', 'end'].includes(k)
      )
        params.set(k, String(v));
    });
    data.value = await get(`/evidence?${params}`);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
watch(() => [props.show, props.reference], loadEvidence, { immediate: true });
</script>
<template>
  <n-drawer :show="show" @update:show="emit('update:show', $event)" :width="520">
    <n-drawer-content title="核对来源" closable>
      <ResourceState :loading="loading" :error="error" @retry="loadEvidence">
        <n-alert
          v-if="data?.missing || data?.status === 'missing' || data?.status === 'deleted'"
          type="warning"
        >
          来源已删除或无法访问。以下只展示引用记录，不代表当前仍能核对原文。
        </n-alert>
        <p class="eyebrow">{{ data?.source?.title || reference?.label || '来源记录' }}</p>
        <h2>{{ data?.chapter?.title || '原文片段' }}</h2>
        <a
          v-if="data?.status === 'available' && reference?.source_version"
          :href="`/api/v1/sources/${reference.source_id}/file?version=${reference.source_version || 1}`"
          target="_blank"
          rel="noopener noreferrer"
        >
          打开对应版本原文件
        </a>
        <p class="muted">
          {{ locationLabel(data?.chapter?.data?.locator || data?.locator) }} · 版本
          {{ reference?.chapter_version || reference?.source_version || 1 }}
        </p>
        <blockquote class="evidence-quote">
          {{ data?.quote || reference?.quote || '没有可展示的原文片段。' }}
        </blockquote>
        <p v-if="data?.chapter?.data?.text" class="evidence-context">
          {{ data.chapter.data.text }}
        </p>
      </ResourceState>
    </n-drawer-content>
  </n-drawer>
</template>
