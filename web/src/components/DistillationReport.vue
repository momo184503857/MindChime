<script setup lang="ts">
import { isAdmin } from '../lib/auth';
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { type Entity, type Reference, textOf } from '../lib/types';
import { download } from '../lib/api';
import { useAction } from '../lib/useData';
import MarkdownText from './MarkdownText.vue';
import EvidenceDrawer from './EvidenceDrawer.vue';

const props = defineProps<{ result: Entity & { cards?: Entity[] } }>();
const router = useRouter();
const { busy, run } = useAction();
const evidence = ref<Reference | null>(null),
  evidenceOpen = ref(false);
const usableCards = computed(() =>
  (props.result.cards || []).filter((c) => c.status !== 'disabled'),
);
const titleMap = computed(() =>
  Object.fromEntries((props.result.cards || []).map((c) => [c.id, c.title])),
);
function resolve(text: string) {
  for (const [id, title] of Object.entries(titleMap.value)) text = text.replaceAll(id, title);
  return text;
}
function generate(kind: 'agent' | 'skill') {
  void router.push({
    path: kind === 'agent' ? '/admin/agents' : '/admin/skills',
    query: { source: props.result.data.source_id, distillation: props.result.id },
  });
}
</script>
<template>
  <article class="distillation-report">
    <p class="muted">
      {{ result.data.method?.name || result.data.method_id }} · 方法 v{{
        result.data.method_version
      }}
      · 结果 v{{ result.version }}
    </p>
    <HelpTip label="方法适配说明" :text="result.data.method?.adaptation || '历史基础蒸馏结果'" />
    <a
      v-if="result.data.method?.upstream"
      :href="result.data.method.upstream"
      target="_blank"
      rel="noopener noreferrer"
      class="text-link"
    >
      方法来源 · {{ result.data.method.license }}
    </a>
    <details v-if="result.data.method?.stages?.length">
      <summary>查看方法阶段与适配版本</summary>
      <ol>
        <li v-for="stage in result.data.method.stages" :key="stage.id">{{ stage.title }}</li>
      </ol>
      <p>上游：{{ result.data.method.upstream_version }}</p>
    </details>
    <div v-if="isAdmin" class="toolbar">
      <n-button
        :loading="busy"
        @click="run(() => download(`/export?kind=distillation&id=${result.id}&format=markdown`))"
      >
        导出 Markdown
      </n-button>
      <n-button
        :loading="busy"
        @click="run(() => download(`/export?kind=distillation&id=${result.id}&format=zip`))"
      >
        导出资产包
      </n-button>
      <n-button
        :disabled="result.status !== 'completed' || !usableCards.length"
        @click="generate('agent')"
      >
        用此结果生成 Agent
      </n-button>
      <n-button
        :disabled="result.status !== 'completed' || !usableCards.length"
        :loading="busy"
        @click="generate('skill')"
      >
        从此结果生成 Skill
      </n-button>
    </div>
    <h3>本次提示词</h3>
    <p>{{ result.data.prompt || '未指定额外重点' }}</p>
    <h3>资料总览</h3>
    <MarkdownText :text="resolve(textOf(result.data.integration?.overview || '尚未生成'))" />
    <div class="heading-with-help">
      <h3>覆盖与质量</h3>
      <HelpTip
        label="覆盖与质量说明"
        text="引用存在性与模型审核分开记录，仍需人工核对。外部书评与联网核验未执行。"
      />
    </div>
    <p>
      选择 {{ result.data.coverage?.selected?.length || 0 }} 章 · 完成
      {{ result.data.coverage?.completed?.length || 0 }} 章 · 候选卡
      {{ result.data.quality?.candidate_cards || 0 }} 张
    </p>
    <ul>
      <li v-for="(failure, i) in result.data.coverage?.failures || []" :key="i">
        {{ failure.stage || '章节处理' }}：{{ failure.reason }}
      </li>
    </ul>
    <ul>
      <li v-for="(warning, i) in result.data.warnings || []" :key="i">{{ warning }}</li>
    </ul>
    <section
      v-for="chapter in result.data.chapter_summaries || []"
      :key="chapter.chapter_id + chapter.summary"
    >
      <h3>{{ chapter.title || '章节摘要' }}</h3>
      <MarkdownText :text="chapter.summary" />
    </section>
    <h3>知识卡与原文证据</h3>
    <section v-for="card in result.cards || []" :key="card.id" class="subtle-note">
      <h4>
        {{ card.title }}
        <small>{{ card.status === 'disabled' ? '候选 · 不参与生成' : '待人工核对' }}</small>
      </h4>
      <MarkdownText :text="card.data.content || ''" />
      <p v-if="card.data.applicability">适用条件：{{ card.data.applicability }}</p>
      <p v-if="card.data.limitations">边界：{{ card.data.limitations }}</p>
      <p v-if="card.data.audit">
        模型审核：{{ card.data.audit.verdict }} · {{ card.data.audit.reason }}
      </p>
      <p v-if="card.data.pressure_test">
        压力测试：{{ card.data.pressure_test.passed ? '通过' : '待修复' }} ·
        {{ card.data.pressure_test.reason }}
      </p>
      <button
        v-for="(ref, i) in card.data.references || []"
        :key="i"
        class="text-link"
        @click="
          evidence = ref;
          evidenceOpen = true;
        "
      >
        核对原文：{{ ref.label }}
      </button>
      <p v-if="!card.data.references?.length" class="muted">未定位到可靠引文，不作为可用能力。</p>
    </section>
    <h3>知识关系</h3>
    <p v-if="!result.data.integration?.relationships?.length" class="muted">
      没有可确认的卡片关系。
    </p>
    <p v-for="(relation, i) in result.data.integration?.relationships || []" :key="i">
      {{ titleMap[relation.from] || relation.from }} → {{ relation.type }} →
      {{ titleMap[relation.to] || relation.to }}：{{ relation.basis }}
    </p>
    <h3>适用边界与局限</h3>
    <ul>
      <li v-for="(limitation, i) in result.data.integration?.limitations || []" :key="i">
        {{ limitation }}
      </li>
    </ul>
    <h3>方法特色成果</h3>
    <p v-if="!result.data.extensions?.length" class="muted">
      此结果没有额外扩展，见公共知识卡和覆盖报告。
    </p>
    <details v-for="(extension, i) in result.data.extensions || []" :key="i" :open="i === 0">
      <summary>{{ extension.title }} · 分组 {{ Number(extension.batch || 0) + 1 }}</summary>
      <section v-for="(section, n) in extension.report?.sections || []" :key="n">
        <h4>{{ section.title }}</h4>
        <MarkdownText :text="resolve(section.content || '')" />
      </section>
      <p v-for="(decision, n) in extension.report?.decisions || []" :key="'decision' + n">
        {{ titleMap[decision.card_id] || '知识卡' }} · {{ decision.verdict }}：{{ decision.reason }}
      </p>
      <section v-for="(test, n) in extension.report?.tests || []" :key="'test' + n">
        <h4>{{ test.question }}</h4>
        <MarkdownText :text="test.answer" />
        <p>{{ test.passed ? '通过' : '待修复' }}：{{ test.reason }}</p>
      </section>
      <p v-for="(repair, n) in extension.report?.repairs || []" :key="'repair' + n">
        {{ titleMap[repair.card_id] || '知识卡' }} · 修复结论 {{ repair.verdict }}：{{
          repair.reason
        }}
      </p>
    </details>

    <EvidenceDrawer v-model:show="evidenceOpen" :reference="evidence" />
  </article>
</template>
<style scoped>
.distillation-report h3 {
  margin: 24px 0 12px;
}
.distillation-report h4 {
  margin: 16px 0 8px;
}
.distillation-report p {
  line-height: 1.8;
  margin: 8px 0;
}
.distillation-report details {
  margin: 16px 0;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.distillation-report summary {
  cursor: pointer;
  font-weight: 600;
}
.distillation-report .subtle-note {
  margin: 12px 0;
}
.distillation-report ul,
.distillation-report ol {
  padding-left: 24px;
  line-height: 1.8;
}
.distillation-report .toolbar {
  flex-wrap: wrap;
  margin-top: 24px;
}
</style>
