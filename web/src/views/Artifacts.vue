<script setup lang="ts">
import { ref, computed } from 'vue';
import { NotebookPen, Plus, Search, Download, Trash2, Quote, ArrowUpRight } from 'lucide-vue-next';
import { get, post, patch, remove, download } from '../lib/api';
import { useResource, useAction, useConfirm } from '../lib/useData';
import { type Entity, type Reference, textOf, dateText, typeLabels } from '../lib/types';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import MarkdownText from '../components/MarkdownText.vue';
import EvidenceDrawer from '../components/EvidenceDrawer.vue';
import ActionChecklist, { type ActionItem } from '../components/ActionChecklist.vue';
const items = ref<ActionItem[]>([]);
const {
  data: artifacts,
  loading,
  error,
  reload,
} = useResource(() => get<Entity[]>('/artifacts'), []);
const { busy, run, message } = useAction();
const confirm = useConfirm();
const q = ref(''),
  filter = ref<string | null>(null),
  selected = ref<Entity | null>(null),
  editing = ref(false),
  title = ref(''),
  content = ref(''),
  type = ref('note'),
  evidence = ref<Reference | null>(null),
  evidenceOpen = ref(false);
const filtered = computed(() =>
  artifacts.value.filter(
    (a) =>
      (!q.value || `${a.title} ${a.data.content || ''}`.includes(q.value)) &&
      (!filter.value || a.data.type === filter.value),
  ),
);
const types = ['note', 'analysis', 'summary', 'action'].map((t) => ({
  label: typeLabels[t],
  value: t,
}));
function edit(a: Entity | null) {
  selected.value = a;
  title.value = a?.title || '';
  content.value = textOf(a?.data.content);
  type.value = a?.data.type || 'note';
  items.value = JSON.parse(JSON.stringify(a?.data.items || []));
  editing.value = true;
}
async function save() {
  if (!title.value.trim() || !content.value.trim()) {
    message.warning('请填写标题与内容');
    return;
  }
  await run(async () => {
    const body = {
      title: title.value,
      data: {
        ...(selected.value?.data || {}),
        type: type.value,
        content: content.value,
        items: type.value === 'action' ? items.value : undefined,
        edited: true,
      },
    };
    const item = selected.value
      ? await patch<Entity>('/artifacts/' + selected.value.id, body)
      : await post<Entity>('/artifacts', body);
    editing.value = false;
    selected.value = item;
    await reload();
  }, '成果已保存');
}
async function updateItems(updated: ActionItem[]) {
  if (!selected.value) return;
  await run(async () => {
    selected.value = await patch<Entity>('/artifacts/' + selected.value!.id, {
      data: { items: updated, edited: true },
    });
    await reload();
  }, '行动状态已保存');
}
async function del(a: Entity) {
  await confirm('删除成果', `删除“${a.title}”，不影响原会话和资料。`, () =>
    run(async () => {
      await remove('/artifacts/' + a.id);
      if (selected.value?.id === a.id) selected.value = null;
      await reload();
    }, '成果已删除'),
  );
}
</script>
<template>
  <PageHeader
    eyebrow="YOUR OWN UNDERSTANDING"
    title="我的成果"
    description="保留真正对你有用的观点、分歧和下一步行动。"
  >
    <n-button type="primary" @click="edit(null)">
      <Plus :size="16" />
      写一条笔记
    </n-button>
  </PageHeader>
  <div class="toolbar">
    <n-input v-model:value="q" class="search-field" placeholder="搜索标题或内容" clearable>
      <template #prefix><Search :size="14" /></template>
    </n-input>
    <n-select
      v-model:value="filter"
      :options="types"
      placeholder="全部类型"
      clearable
      style="width: 160px"
    />
  </div>
  <ResourceState
    :loading="loading"
    :error="error"
    :empty="!filtered.length"
    title="把重要的理解留下来"
    description="你可以从对话保存观点与总结，也可以直接书写自己的笔记。手动编辑不会产生模型调用。"
    @retry="reload()"
  >
    <template #icon><NotebookPen :size="36" :stroke-width="1.3" /></template>
    <template #action><n-button type="primary" @click="edit(null)">写一条笔记</n-button></template>
    <div class="artifact-layout">
      <div class="artifact-list">
        <button
          v-for="a in filtered"
          :key="a.id"
          class="artifact-card surface"
          :class="{ selected: selected?.id === a.id }"
          @click="selected = a"
        >
          <span class="eyebrow">{{ typeLabels[a.data.type] || '个人笔记' }}</span>
          <h3>{{ a.title }}</h3>
          <p>{{ textOf(a.data.content).replace(/[#*`]/g, '').slice(0, 150) }}</p>
          <div>
            <span>{{ dateText(a.updated_at) }}</span>
            <span>{{ a.data.edited ? '已编辑' : '原始保存' }}</span>
          </div>
        </button>
      </div>
      <article v-if="selected" class="artifact-reader surface">
        <div class="section-heading">
          <n-tag :bordered="false" size="small">
            {{ typeLabels[selected.data.type] || '笔记' }}
          </n-tag>
          <div class="inline-actions">
            <n-button size="small" @click="edit(selected)">编辑</n-button>
            <n-button
              size="small"
              @click="
                run(() => download(`/export?kind=artifact&id=${selected!.id}&format=markdown`))
              "
              aria-label="导出成果"
            >
              <Download :size="14" />
            </n-button>
            <n-button size="small" type="error" @click="del(selected)" aria-label="删除成果">
              <Trash2 :size="14" />
            </n-button>
          </div>
        </div>
        <h2>{{ selected.title }}</h2>
        <p class="muted small" style="margin: 10px 0 24px">
          {{ dateText(selected.updated_at) }} ·
          {{ selected.data.edited ? '用户已编辑' : '已保存' }} · 版本 {{ selected.version }}
        </p>
        <MarkdownText :text="textOf(selected.data.content)" />
        <ActionChecklist
          v-if="selected.data.type === 'action'"
          :items="selected.data.items || []"
          @update:items="updateItems"
          :disabled="busy"
        />
        <div v-if="selected.data.references?.length" class="section-spaced">
          <h3>相关来源</h3>
          <div class="chip-row" style="margin-top: 12px">
            <n-button
              v-for="(r, i) in selected.data.references"
              :key="i"
              size="small"
              @click="
                evidence = r;
                evidenceOpen = true;
              "
            >
              <Quote :size="12" />
              {{ r.label || `来源 ${Number(i) + 1}` }}
            </n-button>
          </div>
        </div>
        <RouterLink
          v-if="selected.data.conversation_id"
          :to="'/chat/' + selected.data.conversation_id"
          class="text-link source-link"
        >
          回到原会话
          <ArrowUpRight :size="13" />
        </RouterLink>
      </article>
      <div v-else class="artifact-reader surface reader-empty">
        <NotebookPen :size="28" />
        <h3>选择一份成果继续阅读</h3>
        <p>你的理解和修改，与原始来源一起保留。</p>
      </div>
    </div>
  </ResourceState>
  <n-modal
    v-model:show="editing"
    preset="card"
    :title="selected ? '编辑成果' : '新建笔记'"
    style="width: 900px"
  >
    <n-form>
      <div class="form-grid">
        <n-form-item label="标题"><n-input v-model:value="title" :maxlength="100" /></n-form-item>
        <n-form-item label="类型"><n-select v-model:value="type" :options="types" /></n-form-item>
      </div>
      <n-tabs type="line">
        <n-tab-pane name="edit" tab="编辑 Markdown">
          <n-input
            v-model:value="content"
            type="textarea"
            :autosize="{ minRows: 14, maxRows: 24 }"
            placeholder="写下你自己的理解、前提与行动…"
          />
        </n-tab-pane>
        <n-tab-pane name="preview" tab="阅读预览">
          <MarkdownText :text="content || '还没有内容。'" />
        </n-tab-pane>
      </n-tabs>
      <ActionChecklist v-if="type === 'action'" v-model:items="items" editing />
    </n-form>
    <div class="modal-footer">
      <n-button @click="editing = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="save">保存</n-button>
    </div>
  </n-modal>
  <EvidenceDrawer v-model:show="evidenceOpen" :reference="evidence" />
</template>
<style scoped>
.artifact-layout {
  display: grid;
  grid-template-columns: 310px minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}
.artifact-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.artifact-card {
  padding: 22px;
  text-align: left;
  color: var(--text);
  cursor: pointer;
}
.artifact-card.selected {
  border-color: var(--accent);
}
.artifact-card h3 {
  font-size: 15px;
  margin: 4px 0 10px;
}
.artifact-card > p {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.8;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.artifact-card > div {
  display: flex;
  justify-content: space-between;
  margin-top: 18px;
  font-size: 10px;
  color: var(--muted);
}
.artifact-reader {
  padding: 32px;
  position: sticky;
  top: 92px;
  max-height: calc(100vh - 120px);
  overflow: auto;
  min-height: 450px;
}
.artifact-reader > h2 {
  font-family: 'Songti SC', Georgia, serif;
  font-size: 27px;
  font-weight: 500;
}
.source-link {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 28px;
}
.reader-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  text-align: center;
}
.reader-empty > svg {
  color: var(--accent);
  margin-bottom: 20px;
}
.reader-empty p {
  color: var(--muted);
  font-size: 12px;
  margin-top: 10px;
}
@media (max-width: 1200px) {
  .artifact-layout {
    grid-template-columns: 260px minmax(0, 1fr);
  }
  .artifact-reader {
    padding: 24px;
  }
}
</style>
