<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  Users,
  Plus,
  Sparkles,
  Search,
  MessageSquare,
  Copy,
  Archive,
  Download,
  Trash2,
  ArrowRight,
  BookOpen,
} from 'lucide-vue-next';
import { get, post, patch, remove, download } from '../lib/api';
import { useResource, useAction, useConfirm } from '../lib/useData';
import { type Entity, textOf, dateText } from '../lib/types';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import StatusBadge from '../components/StatusBadge.vue';
import AgentEditor from '../components/AgentEditor.vue';
import MarkdownText from '../components/MarkdownText.vue';
const route = useRoute(),
  router = useRouter();
const {
  data: agents,
  loading,
  error,
  reload,
} = useResource(() => get<Entity[]>('/agents'), [], 10000);
const { busy, run } = useAction();
const confirm = useConfirm();
const sources = ref<Entity[]>([]);
const q = ref(''),
  status = ref<string | null>(null);
const filtered = computed(() =>
  agents.value.filter(
    (a) =>
      (!q.value || `${a.title} ${a.data.purpose || ''}`.includes(q.value)) &&
      (!status.value ||
        (status.value === 'active'
          ? ['active', 'ready', 'available'].includes(a.status)
          : a.status === status.value)),
  ),
);
const editorOpen = ref(false),
  generating = ref(true),
  editing = ref<Entity | null>(null),
  detail = ref<any>(null),
  detailOpen = ref(false),
  compare = ref(false);
const compared = ref<string[]>([]);
function create(generate: boolean) {
  generating.value = generate;
  editing.value = null;
  editorOpen.value = true;
}
function edit(a: Entity) {
  generating.value = false;
  editing.value = a;
  editorOpen.value = true;
}
async function show(a: Entity) {
  await run(async () => {
    detail.value = await get('/agents/' + a.id);
    detailOpen.value = true;
  });
}
async function chat(a: Entity) {
  await run(async () => {
    const c = await post('/conversations', {
      title: `与${a.title}的${a.status === 'draft' ? '试聊' : '对话'}`,
      data: { mode: 'single', agent_ids: [a.id], trial: a.status === 'draft' },
    });
    await router.push('/chat/' + c.id);
  });
}
async function archive(a: Entity) {
  await run(async () => {
    await patch('/agents/' + a.id, { status: a.status === 'archived' ? 'active' : 'archived' });
    await reload();
  }, '状态已更新');
}
async function del(a: Entity) {
  await confirm(
    '删除智能体',
    `删除“${a.title}”不会删除原书或历史消息。运行中的相关任务需要先结束。`,
    () =>
      run(async () => {
        await remove('/agents/' + a.id);
        detailOpen.value = false;
        await reload();
      }, '智能体已删除'),
  );
}
onMounted(() => {
  void run(async () => {
    sources.value = await get('/sources');
  });
  if (route.query.source) create(true);
  if (route.query.selected)
    void run(async () => {
      detail.value = await get('/agents/' + route.query.selected);
      detailOpen.value = true;
    });
});
</script>
<template>
  <PageHeader
    eyebrow="THOUGHT PARTNERS"
    title="思想智能体"
    description="以不同的知识、框架和边界，回应同一个真实问题。"
  >
    <n-button @click="create(false)">
      <template #icon><Plus :size="16" /></template>
      手动组合
    </n-button>
    <n-button type="primary" @click="create(true)">
      <template #icon><Sparkles :size="16" /></template>
      从知识生成
    </n-button>
  </PageHeader>
  <div class="toolbar">
    <n-input v-model:value="q" placeholder="搜索名称或用途" class="search-field" clearable>
      <template #prefix><Search :size="15" /></template>
    </n-input>
    <n-select
      v-model:value="status"
      :options="[
        { label: '可用', value: 'active' },
        { label: '草稿', value: 'draft' },
        { label: '已归档', value: 'archived' },
        { label: '知识不完整', value: 'incomplete' },
      ]"
      clearable
      placeholder="全部状态"
      style="width: 160px"
    />
    <n-button style="margin-left: auto" @click="compare = !compare">
      {{ compare ? '退出比较' : '比较不同视角' }}
    </n-button>
  </div>
  <n-alert v-if="compare" type="info" :show-icon="false" style="margin-bottom: 18px">
    选择 2–3 个智能体，对照它们的知识、用途、框架和共同来源。
  </n-alert>
  <ResourceState
    :loading="loading"
    :error="error"
    :empty="!filtered.length"
    title="让知识拥有一种思考方式"
    description="先蒸馏资料，再为不同的问题创建自己的思想智能体。它们会保留各自的来源与边界。"
    @retry="reload()"
  >
    <template #icon><Users :size="36" :stroke-width="1.3" /></template>
    <template #action>
      <n-button type="primary" @click="create(true)">从知识生成</n-button>
    </template>
    <div class="agent-grid">
      <article
        v-for="a in filtered"
        :key="a.id"
        class="agent-card surface"
        :class="{ 'disabled-asset': ['disabled', 'archived'].includes(a.status) }"
      >
        <div class="agent-head">
          <div class="agent-symbol">{{ a.title.slice(0, 1) }}</div>
          <div class="agent-head-text">
            <button class="agent-name" @click="show(a)">{{ a.title }}</button>
            <div>
              <StatusBadge :status="a.status" />
              <span class="muted small">v{{ a.version }}</span>
            </div>
          </div>
          <n-checkbox
            v-if="compare"
            :checked="compared.includes(a.id)"
            :disabled="!compared.includes(a.id) && compared.length >= 3"
            @update:checked="
              compared = $event ? [...compared, a.id] : compared.filter((id) => id !== a.id)
            "
            :aria-label="'比较' + a.title"
          />
        </div>
        <p class="agent-purpose">{{ a.data.purpose || '尚未填写用途' }}</p>
        <div class="agent-perspective">
          <span>分析视角</span>
          <p>{{ textOf(a.data.perspective) || '等待检查与补充' }}</p>
        </div>
        <div class="agent-knowledge">
          <BookOpen :size="13" />
          {{ a.data.source_ids?.length || 0 }} 份来源 ·
          {{
            a.data.card_ids?.length ? `${a.data.card_ids.length} 张指定卡片` : '绑定范围内可用知识'
          }}
        </div>
        <div class="agent-footer">
          <n-button
            size="small"
            :disabled="['disabled', 'archived'].includes(a.status)"
            @click="chat(a)"
          >
            <template #icon><MessageSquare :size="14" /></template>
            {{ a.status === 'draft' ? '试聊' : '开始对话' }}
          </n-button>
          <n-button text size="small" @click="edit(a)">
            检查与编辑
            <ArrowRight :size="13" />
          </n-button>
        </div>
      </article>
    </div>
    <div v-if="compare && compared.length >= 2" class="comparison surface section-spaced">
      <table class="plain-table">
        <thead>
          <tr>
            <th>比较维度</th>
            <th v-for="a in agents.filter((a) => compared.includes(a.id))" :key="a.id">
              {{ a.title }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="field in [
              { key: 'purpose', label: '用途' },
              { key: 'perspective', label: '视角' },
              { key: 'framework', label: '框架' },
              { key: 'boundaries', label: '边界' },
              { key: 'source_ids', label: '来源标识' },
            ]"
            :key="field.key"
          >
            <td>{{ field.label }}</td>
            <td v-for="a in agents.filter((a) => compared.includes(a.id))" :key="a.id">
              {{
                field.key === 'source_ids'
                  ? (a.data.source_ids || [])
                      .map((id: string) => sources.find((s) => s.id === id)?.title || '来源已失效')
                      .join('、')
                  : textOf(a.data[field.key]) || '未填写'
              }}
            </td>
          </tr>
        </tbody>
      </table>
      <p class="subtle-note">
        相同来源表示共同证据，多个智能体同意一个观点不等于多个独立来源已验证该观点。
      </p>
    </div>
  </ResourceState>
  <AgentEditor
    v-model:show="editorOpen"
    :agent="editing"
    :generate="generating"
    :source-id="String(route.query.source || '') || undefined"
    @saved="reload(true)"
    @job="(job) => router.push('/jobs?selected=' + job.id)"
  />
  <n-drawer v-model:show="detailOpen" :width="600">
    <n-drawer-content :title="detail?.agent?.title || '智能体详情'" closable>
      <template v-if="detail?.agent">
        <div class="inline-actions">
          <StatusBadge :status="detail.agent.status" />
          <span class="muted small">
            版本 {{ detail.agent.version }} · {{ dateText(detail.agent.updated_at) }}
          </span>
        </div>
        <n-alert v-if="detail.agent.status === 'draft'" type="warning" style="margin-top: 18px">
          这是 AI 生成或尚未发布的草稿。请核对来源与设定后保存为可用。
        </n-alert>
        <div
          v-for="field in [
            { key: 'purpose', label: '用途' },
            { key: 'perspective', label: '分析视角' },
            { key: 'framework', label: '思考框架' },
            { key: 'methods', label: '常用方法' },
            { key: 'boundaries', label: '适用边界' },
          ]"
          :key="field.key"
          class="section-spaced"
        >
          <h3>{{ field.label }}</h3>
          <MarkdownText
            :text="textOf(detail.agent.data[field.key]) || '未填写'"
            style="margin-top: 10px"
          />
        </div>
        <n-alert
          v-if="detail.knowledge_summary?.updates_available?.length"
          type="info"
          style="margin-top: 20px"
        >
          <p v-for="update in detail.knowledge_summary.updates_available" :key="update.source_id">
            {{ update.title }}：当前绑定 v{{ update.bound_version }}，可更新到 v{{
              update.current_version
            }}。
          </p>
          <n-button size="small" style="margin-top: 10px" @click="edit(detail.agent)">
            检查知识更新
          </n-button>
        </n-alert>
        <div class="section-spaced">
          <h3>知识范围</h3>
          <p class="muted small">
            {{ detail.knowledge_summary?.cards || 0 }} 张卡片 ·
            {{ detail.knowledge_summary?.chapters || 0 }} 个章节 ·
            {{ detail.knowledge_summary?.unreviewed || 0 }} 张待核对
          </p>
          <p
            v-for="s in detail.knowledge_summary?.coverage || []"
            :key="s.source_id"
            class="field-hint"
          >
            {{ s.title }}
          </p>
        </div>
        <div class="inline-actions section-spaced">
          <n-button type="primary" @click="edit(detail.agent)">编辑版本</n-button>
          <n-button @click="chat(detail.agent)">试聊</n-button>
          <n-button
            @click="
              run(async () => {
                await post('/agents/' + detail.agent.id + '/copy');
                await reload();
              }, '已创建独立副本')
            "
          >
            <Copy :size="14" />
            复制
          </n-button>
          <n-button @click="archive(detail.agent)">
            <Archive :size="14" />
            归档 / 恢复
          </n-button>
          <n-button
            @click="run(() => download(`/export?kind=agent&id=${detail.agent.id}&format=zip`))"
          >
            <Download :size="14" />
            导出便携包
          </n-button>
          <n-button type="error" @click="del(detail.agent)">
            <Trash2 :size="14" />
            删除
          </n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>
<style scoped>
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 22px;
}
.agent-card {
  padding: 24px;
  display: flex;
  flex-direction: column;
  min-height: 310px;
}
.agent-head {
  display: flex;
  gap: 14px;
  align-items: center;
}
.agent-symbol {
  width: 44px;
  height: 44px;
  background: var(--accent-soft);
  color: var(--accent);
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-family: 'Songti SC', Georgia, serif;
  font-size: 22px;
}
.agent-head-text {
  flex: 1;
  min-width: 0;
}
.agent-head-text > div {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 6px;
}
.agent-name {
  padding: 0;
  border: 0;
  background: transparent;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  cursor: pointer;
  text-align: left;
}
.agent-purpose {
  font-size: 13px;
  margin: 22px 0 16px;
  line-height: 1.8;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.agent-perspective {
  padding-left: 12px;
  border-left: 2px solid var(--border);
  margin-bottom: 22px;
}
.agent-perspective span {
  font-size: 10px;
  letter-spacing: 1px;
  color: var(--muted);
}
.agent-perspective p {
  font-size: 12px;
  margin-top: 5px;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.agent-knowledge {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 10px;
  color: var(--muted);
  margin-top: auto;
}
.agent-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-top: 1px solid var(--border);
  margin-top: 18px;
  padding-top: 16px;
}
.comparison {
  overflow: auto;
}
.comparison td {
  white-space: pre-line;
  min-width: 180px;
}
.comparison td:first-child {
  min-width: 90px;
  color: var(--muted);
}
</style>
