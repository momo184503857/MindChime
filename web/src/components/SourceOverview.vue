<script setup lang="ts">
import { computed, ref } from 'vue';
import { get } from '../lib/api';
import ResourceState from './ResourceState.vue';
import { type Entity, dateText, textOf } from '../lib/types';
import MarkdownText from './MarkdownText.vue';
const props = defineProps<{ source: Entity; chapters: Entity[]; versions: Entity[] }>();
const historyOpen = ref(false),
  historyLoading = ref(false),
  historyError = ref('');
const historical = ref<any>(null);
const historyVersion = ref(0);
async function viewVersion(version: number) {
  historyVersion.value = version;
  historyOpen.value = true;
  historyLoading.value = true;
  historyError.value = '';
  try {
    historical.value = await get(`/sources/${props.source.id}?version=${version}`);
  } catch (error) {
    historyError.value = (error as Error).message;
  } finally {
    historyLoading.value = false;
  }
}
const report = computed(() => props.source.data.distillation || {});
const coverage = computed(() => props.source.data.coverage || {});
const overview = computed(() => {
  let text = textOf(
    report.value.overview ||
      props.source.data.overview ||
      props.source.data.summary ||
      '尚未生成总览。完成章节蒸馏后，这里会展示真实处理结果。',
  );
  for (const c of props.chapters) text = text.replaceAll(c.id, c.title);
  return text;
});
function chapterName(value: any) {
  const id = typeof value === 'string' ? value : value?.chapter_id || value?.id;
  return props.chapters.find((c) => c.id === id)?.title || value?.title || '历史章节';
}
</script>
<template>
  <section class="surface panel-pad">
    <h2>蒸馏总览</h2>
    <MarkdownText :text="overview" style="margin-top: 16px" />
    <section class="section-spaced">
      <h3>真实覆盖范围</h3>
      <div v-if="coverage.selected" class="coverage-summary">
        <span>
          选中
          <strong>{{ coverage.selected.length }}</strong>
        </span>
        <span>
          成功
          <strong>{{ coverage.completed?.length || 0 }}</strong>
        </span>
        <span>
          失败
          <strong>{{ coverage.failures?.length || 0 }}</strong>
        </span>
        <span>
          未处理
          <strong>{{ coverage.omitted?.length || 0 }}</strong>
        </span>
      </div>
      <p v-else class="field-hint">尚无蒸馏任务报告。</p>
      <div class="chip-row" style="margin-top: 12px">
        <n-tag
          v-for="chapter in coverage.completed || []"
          :key="String(chapter)"
          type="success"
          size="small"
          :bordered="false"
        >
          {{ chapterName(chapter) }} · 已完成
        </n-tag>
        <n-tag
          v-for="chapter in coverage.omitted || []"
          :key="String(chapter)"
          size="small"
          :bordered="false"
        >
          {{ chapterName(chapter) }} · 未处理
        </n-tag>
      </div>
      <n-alert
        v-for="(failure, i) in coverage.failures || []"
        :key="i"
        type="warning"
        style="margin-top: 12px"
      >
        {{ chapterName(failure) }}：{{
          failure.reason || failure.error || '处理失败，可在任务中心重试该项。'
        }}
      </n-alert>
      <RouterLink
        v-if="coverage.job_id || source.data.latest_distill_job_id"
        :to="'/jobs?selected=' + (coverage.job_id || source.data.latest_distill_job_id)"
        class="text-link"
        style="display: inline-block; margin-top: 16px"
      >
        查看处理任务 →
      </RouterLink>
    </section>
    <section class="section-spaced" v-if="report.limitations?.length">
      <h3>局限与待核对内容</h3>
      <ul class="report-list">
        <li v-for="(limitation, i) in report.limitations" :key="i">{{ textOf(limitation) }}</li>
      </ul>
    </section>
    <section class="section-spaced" v-if="report.relationships?.length">
      <h3>知识关系清单</h3>
      <div
        v-for="(relation, i) in report.relationships"
        :key="i"
        class="subtle-note"
        style="margin-top: 10px"
      >
        {{
          typeof relation === 'string'
            ? relation
            : relation.description ||
              relation.evidence ||
              relation.relation ||
              '查看图谱中的关系候选'
        }}
      </div>
    </section>
    <section class="section-spaced">
      <h3>资料版本记录</h3>
      <div class="list-item" v-for="version in versions" :key="version.version">
        <span>版本 {{ version.version }}</span>
        <n-button size="small" @click="viewVersion(version.version)">查看历史内容</n-button>
        <span class="muted small">{{ dateText(version.updated_at || version.created_at) }}</span>
        <span class="muted small">{{ version.data.chapter_ids?.length || 0 }} 个章节 / 分段</span>
      </div>
      <p class="muted small" v-if="!versions.length">当前版本 {{ source.version }}</p>
    </section>
  </section>
  <n-modal
    v-model:show="historyOpen"
    preset="card"
    title="历史知识与处理报告（只读）"
    style="width: 850px"
  >
    <ResourceState
      :loading="historyLoading"
      :error="historyError"
      @retry="viewVersion(historyVersion)"
    >
      <template v-if="historical">
        <h2>{{ historical.source.title }} · v{{ historyVersion }}</h2>
        <h3>总览与处理范围</h3>
        <MarkdownText :text="textOf(historical.source.data.distillation || '尚无整合结果')" />
        <p>{{ textOf(historical.source.data.coverage || {}) }}</p>
        <h3>章节摘要</h3>
        <section v-for="chapter in historical.chapters" :key="chapter.id">
          <h4>{{ chapter.title }}</h4>
          <MarkdownText :text="chapter.data.latest_summary || '该版本尚无摘要'" />
        </section>
        <h3>知识卡</h3>
        <section v-for="card in historical.cards" :key="card.id">
          <h4>{{ card.title }} · v{{ card.version }}</h4>
          <MarkdownText :text="card.data.content" />
        </section>
      </template>
    </ResourceState>
  </n-modal>
</template>
<style scoped>
.coverage-summary {
  display: flex;
  gap: 28px;
  margin: 16px 0;
  font-size: 12px;
  color: var(--muted);
}
.coverage-summary strong {
  color: var(--text);
  font-size: 20px;
  font-weight: 500;
  margin-left: 6px;
}
.report-list {
  padding-left: 20px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.9;
  margin-top: 12px;
}
.report-list li {
  margin: 8px 0;
}
</style>
