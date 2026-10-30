<script setup lang="ts">
import { computed } from 'vue';
import { get } from '../../lib/api';
import { useResource } from '../../lib/useData';
import { type Entity, liveJobStates } from '../../lib/types';
import { adminNav } from '../../lib/navigation';
import PageHeader from '../../components/PageHeader.vue';
import ResourceState from '../../components/ResourceState.vue';
import JobStrip from '../../components/JobStrip.vue';
const { data, loading, error, reload } = useResource(
  async () => {
    const [dashboard, jobs] = await Promise.all([get<any>('/dashboard'), get<Entity[]>('/jobs')]);
    return { dashboard, jobs };
  },
  { dashboard: {}, jobs: [] },
  8000,
);
const pending = computed(() =>
  data.value.jobs.filter((j) =>
    [...liveJobStates, 'paused', 'interrupted', 'waiting', 'waiting_error'].includes(j.status),
  ),
);
const failed = computed(() =>
  data.value.jobs.filter((j) => ['failed', 'partial', 'partial_completed'].includes(j.status)),
);
const counts = computed(() => data.value.dashboard.counts || {});
const metrics = [
  { key: 'source', label: '资料', path: '/admin/library' },
  { key: 'agent', label: '智能体', path: '/admin/agents' },
  { key: 'skill', label: 'Skills', path: '/admin/skills' },
  { key: 'card', label: '知识卡', path: '/admin/library' },
];
</script>
<template>
  <PageHeader title="管理概览" description="维护知识资产，处理执行任务，管理模型与本地数据。">
    <RouterLink to="/" class="text-link">返回前台 →</RouterLink>
  </PageHeader>
  <ResourceState :loading="loading" :error="error" @retry="reload()">
    <div class="admin-metrics">
      <RouterLink
        v-for="metric in metrics"
        :key="metric.key"
        :to="metric.path"
        class="surface panel-pad"
      >
        <span class="muted">{{ metric.label }}</span>
        <strong>{{ counts[metric.key] ?? counts[metric.key + 's'] ?? 0 }}</strong>
      </RouterLink>
    </div>
    <section class="surface panel-pad section-spaced">
      <h2>维护入口</h2>
      <div class="admin-shortcuts">
        <RouterLink
          v-for="item in adminNav.slice(1)"
          :key="item.path"
          :to="item.path"
          class="text-link"
        >
          <component :is="item.icon" :size="17" />
          {{ item.label }}
        </RouterLink>
      </div>
    </section>
    <section class="section-spaced">
      <div class="section-heading">
        <h2>待处理任务 · {{ pending.length }}</h2>
        <RouterLink to="/admin/jobs" class="text-link">全部任务 →</RouterLink>
      </div>
      <JobStrip
        v-for="job in pending.slice(0, 4)"
        :key="job.id"
        :job="job"
        @changed="reload(true)"
      />
      <p v-if="!pending.length" class="surface panel-pad muted">当前没有待处理任务。</p>
    </section>
    <section class="section-spaced">
      <h2>失败或部分完成 · {{ failed.length }}</h2>
      <JobStrip
        v-for="job in failed.slice(0, 4)"
        :key="job.id"
        :job="job"
        @changed="reload(true)"
      />
      <p v-if="!failed.length" class="surface panel-pad muted">当前没有需要重试的任务。</p>
    </section>
  </ResourceState>
</template>
<style scoped>
.admin-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
}
.admin-metrics strong {
  display: block;
  font-size: 30px;
  margin-top: 12px;
  font-weight: 500;
}
.admin-shortcuts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
  margin-top: 24px;
}
.admin-shortcuts a {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
