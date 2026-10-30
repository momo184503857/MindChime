<script setup lang="ts">
import { isAdmin } from '../../lib/auth';
import { orderSourceChapters } from '../../lib/sourceView';
import { switchArea } from '../../lib/navigation';
import { ref, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, download } from '../../lib/api';
import { useResource, useAction } from '../../lib/useData';
import { type Entity, type Reference, textOf, typeLabels, locationLabel } from '../../lib/types';
import PageHeader from '../../components/PageHeader.vue';
import ResourceState from '../../components/ResourceState.vue';
import MarkdownText from '../../components/MarkdownText.vue';
import EvidenceDrawer from '../../components/EvidenceDrawer.vue';
import ReferenceLinks from '../../components/ReferenceLinks.vue';
import SourceOverview from '../../components/SourceOverview.vue';
import DistillationResults from '../../components/DistillationResults.vue';
import StatusBadge from '../../components/StatusBadge.vue';
const route = useRoute(),
  router = useRouter();
const id = computed(() => String(route.params.id));
const { data, loading, error, reload } = useResource(
  async () => {
    const detail = orderSourceChapters(await get<any>('/sources/' + id.value));
    const current = detail.source?.data.active_distillation_id;
    const result = current
      ? await get<Entity & { cards: Entity[] }>('/distillations/' + current)
      : null;
    const userCards = detail.cards.filter(
      (c: Entity) =>
        !c.data.distillation_id &&
        ['user', 'user_original', 'user_modified'].includes(c.data.edit_origin),
    );
    return { ...detail, readingCards: [...(result?.cards || []), ...userCards], result };
  },
  { source: null, chapters: [], cards: [], readingCards: [], versions: [], result: null },
);
const source = computed<Entity | null>(() => data.value.source);
const tab = ref(String(route.query.tab || 'chapters'));
const chapterId = ref(String(route.query.chapter || ''));
const chapter = computed<Entity | undefined>(() =>
  data.value.chapters.find((c: Entity) => c.id === chapterId.value),
);
const evidence = ref<Reference | null>(null),
  evidenceOpen = ref(false);
const { run } = useAction();
const cardType = ref<string | null>(null);
const visibleCards = computed<Entity[]>(() =>
  data.value.readingCards.filter((c: Entity) => !cardType.value || c.data.type === cardType.value),
);
watch(id, () => {
  chapterId.value = String(route.query.chapter || '');
  void reload();
});
watch(
  () => data.value.chapters,
  (chapters) => {
    if (!chapters.some((c: Entity) => c.id === chapterId.value))
      chapterId.value = chapters[0]?.id || '';
  },
);
watch([tab, chapterId], () => {
  void router.replace({
    query: { ...route.query, tab: tab.value, chapter: chapterId.value || undefined },
  });
});
watch(
  () => route.query,
  (query) => {
    tab.value = String(query.tab || 'chapters');
    if (query.chapter) chapterId.value = String(query.chapter);
  },
);
function show(ref: Reference) {
  evidence.value = ref;
  evidenceOpen.value = true;
}
</script>
<template>
  <RouterLink to="/library" class="back-link">← 返回书架</RouterLink>
  <ResourceState :loading="loading" :error="error" @retry="reload()">
    <template #action><n-button @click="router.push('/library')">返回书架</n-button></template>
    <template v-if="source">
      <PageHeader
        description-is-metadata
        :title="source.title"
        :description="source.data.author || '作者未填写'"
      >
        <n-button v-if="isAdmin" @click="run(() => download(`/export?kind=source&id=${id}&format=markdown`))">
          导出
        </n-button>
        <n-button v-if="isAdmin" @click="router.push(switchArea(route, 'admin'))">管理此资料</n-button>
      </PageHeader>
      <div class="surface panel-pad inline-actions">
        <StatusBadge :status="source.status" />
        <span>版本 {{ source.version }}</span>
        <a
          v-if="source.data.original_path || source.data.file_path || source.data.format"
          :href="`/api/v1/sources/${id}/file`"
          target="_blank"
          rel="noopener noreferrer"
          class="text-link"
        >
          查看原文件
        </a>
      </div>
      <div v-if="!source.data.active_distillation_id" class="inline-actions section-spaced">
        <n-tag size="small">未设置当前结果</n-tag>
        <HelpTip
          label="当前蒸馏结果说明"
          text="可以阅读原文；在后台选择当前结果后，这里会展示对应批次知识。"
        />
      </div>
      <n-tabs v-model:value="tab" type="line" class="source-tabs">
        <n-tab-pane name="chapters" tab="章节与原文">
          <div class="chapter-layout surface">
            <aside class="chapter-list" aria-label="章节目录">
              <button
                v-for="c in data.chapters"
                :key="c.id"
                class="reader-chapter"
                :aria-current="chapterId === c.id ? 'true' : undefined"
                @click="chapterId = c.id"
              >
                {{ c.title }}
              </button>
            </aside>
            <article class="chapter-reader" v-if="chapter">
              <p class="eyebrow">{{ locationLabel(chapter.data.locator) }}</p>
              <h2>{{ chapter.title }}</h2>
              <div v-if="chapter.data.ocr" class="inline-actions">
                <n-tag size="small">OCR</n-tag>
                <HelpTip label="OCR 内容说明" text="此段来自 OCR，请对照原文件核对。" />
              </div>
              <p class="source-text" v-if="chapter.data.text">{{ chapter.data.text }}</p>
              <p class="muted" v-else>
                暂无可读文字。
                <HelpTip label="扫描页识别说明" text="可前往后台识别并核对。" />
              </p>
            </article>
            <p v-else class="panel-pad muted">暂无可读章节。</p>
          </div>
        </n-tab-pane>
        <n-tab-pane name="cards" :tab="`知识卡 (${data.readingCards.length})`">
          <div class="toolbar">
            <HelpTip label="知识卡批次说明">
              仅展示当前结果及独立用户补充。其他批次请在“蒸馏结果”中查看。
            </HelpTip>
            <n-select
              v-model:value="cardType"
              clearable
              placeholder="全部知识卡类型"
              style="width: 180px"
              :options="
                ['concept', 'claim', 'method', 'boundary'].map((value) => ({
                  value,
                  label: typeLabels[value],
                }))
              "
            />
          </div>
          <div class="knowledge-grid">
            <article
              v-for="card in visibleCards"
              :key="card.id"
              class="surface panel-pad"
              :class="{ 'disabled-asset': card.status === 'disabled' }"
            >
              <div class="inline-actions">
                <n-tag size="small">{{ typeLabels[card.data.type] || card.data.type }}</n-tag>
                <StatusBadge
                  :status="
                    card.status === 'disabled' ? card.status : card.data.review_status || 'pending'
                  "
                />
              </div>
              <h3>{{ card.title }}</h3>
              <MarkdownText :text="textOf(card.data.content)" />
              <ReferenceLinks :references="card.data.references || []" @open="show" />
            </article>
          </div>
          <p v-if="!visibleCards.length" class="muted panel-pad">当前范围没有匹配的知识卡。</p>
        </n-tab-pane>
        <n-tab-pane name="distillations" tab="蒸馏结果">
          <DistillationResults :source="source" />
        </n-tab-pane>
        <n-tab-pane name="overview" tab="总览与覆盖">
          <SourceOverview :source="source" :chapters="data.chapters" :versions="data.versions" />
        </n-tab-pane>
      </n-tabs>
      <EvidenceDrawer v-model:show="evidenceOpen" :reference="evidence" />
    </template>
  </ResourceState>
</template>
<style scoped>
.chapter-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  min-height: 420px;
}
.chapter-list {
  border-right: 1px solid var(--border);
  padding: 12px;
}
.reader-chapter {
  display: block;
  width: 100%;
  padding: 12px;
  text-align: left;
  border: 0;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  border-radius: 6px;
}
.reader-chapter[aria-current] {
  background: var(--accent-soft);
  color: var(--accent);
}
.chapter-reader {
  padding: 28px;
  min-width: 0;
}
.source-text {
  white-space: pre-wrap;
  line-height: 1.9;
  margin-top: 20px;
}
.knowledge-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}
.knowledge-grid h3 {
  margin: 16px 0;
}
.source-tabs {
  margin-top: 20px;
}
</style>
