<script setup lang="ts">
import { jobPath } from '../lib/navigation';
import { computed } from 'vue';
import { type Entity, textOf, liveJobStates, jobLabels } from '../lib/types';
import { post } from '../lib/api';
import { useAction } from '../lib/useData';
import StatusBadge from './StatusBadge.vue';
const props = defineProps<{ job: Entity }>();
const emit = defineEmits(['changed']);
const { busy, run } = useAction();
const status = computed(() => props.job.status);
async function act(action: string) {
  await run(
    async () => {
      await post(`/jobs/${props.job.id}/${action}`);
      emit('changed');
    },
    action === 'pause'
      ? '当前模型调用完成后暂停'
      : action === 'cancel'
        ? '已请求结束'
        : '任务状态已更新',
  );
}
</script>
<template>
  <section class="job-strip" aria-live="polite">
    <div class="job-strip-info">
      <StatusBadge :status="status" />
      <strong>{{ jobLabels[job.data.kind] || job.title }}</strong>
      <span class="muted">{{ textOf(job.data.stage || job.data.progress?.stage || '') }}</span>
      <span v-if="job.data.error" class="error-text">{{ textOf(job.data.error) }}</span>
    </div>
    <div class="inline-actions">
      <n-button
        v-if="
          ['running', 'processing'].includes(status) &&
          ['discussion', 'distill', 'thought_distill'].includes(job.data.kind)
        "
        size="small"
        :loading="busy"
        @click="act('pause')"
      >
        暂停
      </n-button>
      <n-button
        v-if="['paused', 'interrupted'].includes(status)"
        size="small"
        :loading="busy"
        @click="act('resume')"
      >
        确认继续
      </n-button>
      <n-button
        v-if="
          [
            'failed',
            'partial',
            'partial_completed',
            'waiting',
            'waiting_error',
            'interrupted',
          ].includes(status)
        "
        size="small"
        :loading="busy"
        @click="act('retry')"
      >
        重试未完成项
      </n-button>
      <n-button
        v-if="
          ['failed', 'waiting', 'waiting_error', 'paused'].includes(status) &&
          job.data.failed_agent_id
        "
        size="small"
        @click="act('skip')"
      >
        跳过该成员本场发言
      </n-button>
      <n-button
        v-if="
          [
            ...liveJobStates,
            'paused',
            'waiting',
            'waiting_error',
            'failed',
            'interrupted',
          ].includes(status)
        "
        size="small"
        :loading="busy"
        @click="act('cancel')"
      >
        立即结束
      </n-button>
      <RouterLink :to="jobPath(job.id)" class="text-link">详情</RouterLink>
    </div>
  </section>
</template>
