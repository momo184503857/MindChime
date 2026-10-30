<script setup lang="ts">
import { computed, watch } from 'vue';
import { get } from '../lib/api';
import { useResource } from '../lib/useData';
import { type Entity, liveJobStates } from '../lib/types';
import JobStrip from './JobStrip.vue';
const props = defineProps<{ runId: string }>();
const emit = defineEmits<{ (e: 'changed'): void; (e: 'pending', value: boolean): void }>();
const { data, error, reload } = useResource(
  async () =>
    (await get<Entity[]>('/jobs')).filter(
      (j) => j.data.input?.run_id === props.runId && !['completed', 'cancelled'].includes(j.status),
    ),
  [],
  4000,
);
const pending = computed(() =>
  data.value.some((j) =>
    [...liveJobStates, 'paused', 'interrupted', 'waiting_error'].includes(j.status),
  ),
);
watch(pending, (value) => emit('pending', value), { immediate: true });
watch(
  () => props.runId,
  () => void reload(),
);
</script>
<template>
  <n-alert v-if="error" type="error">
    实践任务状态加载失败：{{ error }}
    <n-button text @click="reload()">重试</n-button>
  </n-alert>
  <JobStrip
    v-for="job in data"
    :key="job.id"
    :job="job"
    @changed="
      reload(true);
      emit('changed');
    "
  />
</template>
