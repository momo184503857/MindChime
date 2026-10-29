<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Activity, RefreshCw, CheckCircle2, Clock, ArrowUpRight } from 'lucide-vue-next';
import { get, events } from '../lib/api';
import { useResource } from '../lib/useData';
import { type Entity, textOf, dateText, stateLabels } from '../lib/types';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import StatusBadge from '../components/StatusBadge.vue';
import JobStrip from '../components/JobStrip.vue';
import MarkdownText from '../components/MarkdownText.vue';
const route = useRoute(),
  router = useRouter();
const { data: jobs, loading, error, reload } = useResource(() => get<Entity[]>('/jobs'), [], 4000);
const filter = ref<string | null>(null),
  selected = ref<string | null>(String(route.query.selected || '') || null);
const filtered = computed(() =>
  jobs.value.filter((j) => !filter.value || j.status === filter.value),
);
const job = computed(() => jobs.value.find((j) => j.id === selected.value));
const statuses = computed(() =>
  [...new Set(jobs.value.map((j) => j.status))].map((s) => ({
    label: stateLabels[s] || s,
    value: s,
  })),
);
const types: Record<string, string> = {
  distill: '内容蒸馏',
  ocr: '扫描页识别',
  agent_generate: '生成智能体',
  chat: '对话回复',
  discussion: '思想圆桌',
  summary: '讨论总结',
  artifact_generate: '整理成果',
  skill_generate: '生成实践方法',
  skill_step: '实践引导',
  memory_extract: '提取记忆候选',
  graph_generate: '生成知识关系',
  embedding: '更新检索索引',
};
let stop: (() => void) | undefined;
onMounted(() => {
  stop = events('jobs', () => void reload(true));
});
onUnmounted(() => stop?.());
const steps = computed<Array<Record<string, any> & { key: string }>>(() =>
  Object.entries(job.value?.data.steps || {}).map(([key, value]) => ({
    key,
    ...(value as Record<string, any>),
  })),
);
function openRelated(j: Entity) {
  const input = j.data.input || {};
  if (input.conversation_id) void router.push('/chat/' + input.conversation_id);
  else if (input.source_id) void router.push('/library/' + input.source_id);
  else if (j.data.kind?.includes('agent')) void router.push('/agents');
  else if (j.data.kind?.includes('skill')) void router.push('/skills');
  else if (j.data.kind?.includes('memory')) void router.push('/memories');
  else if (j.data.kind?.includes('graph')) void router.push('/graph');
  else if (j.data.kind?.includes('artifact')) void router.push('/artifacts');
}
</script>
<template>
  <PageHeader
    eyebrow="TASK CENTER"
    title="任务中心"
    description="查看真实处理进度、保留下来的结果，以及下一步可以做什么。"
  >
    <n-button @click="reload()">
      <RefreshCw :size="15" />
      刷新
    </n-button>
  </PageHeader>
  <div class="toolbar">
    <n-select
      v-model:value="filter"
      :options="statuses"
      clearable
      placeholder="全部状态"
      style="width: 170px"
    />
    <span class="muted small">刷新或关闭网页不会重复提交任务。</span>
  </div>
  <ResourceState
    :loading="loading"
    :error="error"
    :empty="!filtered.length"
    title="目前没有任务"
    description="导入后的 OCR、蒸馏、智能体生成和讨论任务都会出现在这里。"
    @retry="reload()"
  >
    <template #icon><Activity :size="36" :stroke-width="1.3" /></template>
    <div class="surface table-scroll">
      <table class="plain-table">
        <thead>
          <tr>
            <th>任务</th>
            <th>状态</th>
            <th>当前阶段</th>
            <th>创建时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in filtered" :key="j.id" :class="{ selected: j.id === selected }">
            <td>
              <button class="task-name" @click="selected = j.id">
                {{ types[j.data.kind] || j.title
                }}{{ j.data.method_name ? ' · ' + j.data.method_name : '' }}
              </button>
              <small class="task-id">{{ j.id.slice(0, 8) }}</small>
            </td>
            <td><StatusBadge :status="j.status" /></td>
            <td>
              {{ textOf(j.data.stage) || '等待处理' }}
              <div v-if="j.data.error" class="error-text">{{ textOf(j.data.error) }}</div>
            </td>
            <td>{{ dateText(j.created_at) }}</td>
            <td><n-button text size="small" @click="selected = j.id">查看详情</n-button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </ResourceState>
  <n-drawer
    :show="!!job"
    @update:show="
      (v: boolean) => {
        if (!v) selected = null;
      }
    "
    :width="660"
  >
    <n-drawer-content :title="job ? types[job.data.kind] || job.title : '任务详情'" closable>
      <template v-if="job">
        <JobStrip :job="job" @changed="reload(true)" />
        <p class="muted small">
          创建于 {{ dateText(job.created_at) }} · 最近更新 {{ dateText(job.updated_at) }}
        </p>
        <n-button @click="openRelated(job)" style="margin-top: 16px">
          查看相关资料 / 结果
          <ArrowUpRight :size="14" />
        </n-button>
        <section class="section-spaced">
          <h3>当前进度</h3>
          <p style="margin-top: 8px">{{ textOf(job.data.stage) }}</p>
          <p v-if="job.data.completed_chapters != null" class="muted small">
            已完成 {{ job.data.completed_chapters }} / {{ job.data.total_chapters || '?' }} 个章节
          </p>
          <n-alert v-if="job.data.error" type="error" style="margin-top: 12px">
            {{ textOf(job.data.error) }}
            <p>成功部分已保留。请先确认模型配置和失败原因，再重试未完成项。</p>
          </n-alert>
        </section>
        <section class="section-spaced">
          <h3>调用与保存状态</h3>
          <div v-for="(step, index) in steps" :key="step.key" class="step-state">
            <CheckCircle2 v-if="step.status === 'completed'" :size="16" class="accent" />
            <Clock v-else :size="16" class="muted" />
            <div>
              <strong>步骤 {{ Number(index) + 1 }}</strong>
              <span>{{ stateLabels[step.status] || step.status }}</span>
              <small v-if="step.result?.usage">模型用量：{{ textOf(step.result.usage) }}</small>
            </div>
          </div>
          <p v-if="!steps.length" class="muted small">还没有开始模型调用。</p>
        </section>
        <n-alert v-if="job.status === 'interrupted'" type="warning" style="margin-top: 20px">
          上次调用可能已被模型服务接收。恢复前请确认实际状态；系统不会自动从头再次调用。
        </n-alert>
        <section class="section-spaced" v-if="job.data.result">
          <h3>结果摘要</h3>
          <MarkdownText v-if="typeof job.data.result === 'string'" :text="job.data.result" />
          <p v-else class="muted small">
            结果已保存到对应资料、对话或增强功能页面，可通过上方入口查看。
          </p>
        </section>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>
<style scoped>
.task-name {
  border: 0;
  background: none;
  color: var(--text);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
  padding: 0;
  text-align: left;
}
.task-name:hover {
  color: var(--accent);
}
.task-id {
  display: block;
  font-size: 9px;
  color: var(--muted);
  margin-top: 5px;
  font-family: monospace;
}
.selected {
  background: var(--accent-soft);
}
.step-state {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.step-state > div {
  flex: 1;
}
.step-state strong {
  font-size: 12px;
  font-weight: 500;
}
.step-state span {
  float: right;
  font-size: 11px;
  color: var(--muted);
}
.step-state small {
  display: block;
  font-size: 10px;
  color: var(--muted);
  margin-top: 6px;
}
.accent {
  color: var(--accent);
}
</style>
