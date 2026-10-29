<script setup lang="ts">
import { ref, watch, computed, onMounted, onUnmounted, nextTick } from 'vue';
import { useRouter } from 'vue-router';
import cytoscape from 'cytoscape';
import { Network, List, Plus, Sparkles, Expand, Check, Link2, Quote } from 'lucide-vue-next';
import { get, post, patch } from '../lib/api';
import { useResource, useAction } from '../lib/useData';
import { type Entity, type Reference, typeLabels, textOf, requestId } from '../lib/types';
import { useAppStore } from '../stores/app';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import StatusBadge from '../components/StatusBadge.vue';
import MarkdownText from '../components/MarkdownText.vue';
import EvidenceDrawer from '../components/EvidenceDrawer.vue';
const router = useRouter(),
  app = useAppStore();
const {
  data: graph,
  loading,
  error,
  reload,
} = useResource(() => get<{ nodes: Entity[]; edges: Entity[] }>('/graph'), {
  nodes: [],
  edges: [],
});
const { busy, run, message } = useAction();
const sources = ref<Entity[]>([]);
const sourceId = ref<string | null>(null),
  mode = ref('graph'),
  kind = ref<string | null>(null),
  container = ref<HTMLElement | null>(null),
  selected = ref<Entity | null>(null),
  detailOpen = ref(false),
  generateOpen = ref(false),
  generateSources = ref<string[]>([]),
  editOpen = ref(false),
  editing = ref<Entity | null>(null),
  fromId = ref<string | null>(null),
  toId = ref<string | null>(null),
  relationType = ref('support'),
  relationEvidence = ref('');
const evidence = ref<Reference | null>(null),
  evidenceOpen = ref(false);
const relationOptions = ['support', 'limit', 'refute', 'apply', 'similar'].map((v) => ({
  label: typeLabels[v],
  value: v,
}));
const filteredNodes = computed(() =>
  graph.value.nodes.filter(
    (n) =>
      (!sourceId.value ||
        (n.data.source_ids || []).includes(sourceId.value) ||
        n.id === sourceId.value) &&
      (!kind.value || n.data.type === kind.value),
  ),
);
const filteredIds = computed(() => new Set(filteredNodes.value.map((n) => n.id)));
const filteredEdges = computed(() =>
  graph.value.edges.filter(
    (e) => filteredIds.value.has(e.data.from_id) && filteredIds.value.has(e.data.to_id),
  ),
);
let cy: cytoscape.Core | undefined, observer: ResizeObserver | undefined;
function nodeName(id: string) {
  return graph.value.nodes.find((n) => n.id === id)?.title || '来源已失效';
}
async function renderGraph() {
  await nextTick();
  if (!container.value || mode.value !== 'graph') return;
  cy?.destroy();
  const dark = app.dark;
  cy = cytoscape({
    container: container.value,
    elements: [
      ...filteredNodes.value.map((n) => ({
        data: {
          id: n.id,
          label: n.title,
          type: n.data.type || 'concept',
          disabled: n.status === 'disabled' ? 1 : 0,
        },
        classes: n.status === 'disabled' ? 'disabled' : '',
      })),
      ...filteredEdges.value.map((e) => ({
        data: {
          id: e.id,
          source: e.data.from_id,
          target: e.data.to_id,
          label: typeLabels[e.data.type] || e.data.type,
        },
        classes: `${e.status === 'disabled' ? 'disabled' : ''} ${e.status === 'candidate' ? 'candidate' : ''}`,
      })),
    ],
    style: [
      {
        selector: 'node',
        style: {
          'background-color': dark ? '#426f5e' : '#b7d3c4',
          'border-color': dark ? '#7bb29a' : '#6c9b84',
          'border-width': 1.5,
          label: 'data(label)',
          color: dark ? '#dce9e1' : '#334e40',
          'font-size': 11,
          'text-wrap': 'wrap',
          'text-max-width': '105px',
          'text-valign': 'bottom',
          'text-margin-y': 9,
          width: 26,
          height: 26,
        },
      },
      {
        selector: 'node[type="method"]',
        style: {
          shape: 'round-rectangle',
          'background-color': dark ? '#756641' : '#e7d5a8',
          'border-color': '#af9662',
        },
      },
      {
        selector: 'node[type="boundary"]',
        style: {
          shape: 'diamond',
          'background-color': dark ? '#6d5667' : '#d8c7d5',
          'border-color': '#aa87a4',
        },
      },
      {
        selector: 'edge',
        style: {
          width: 1.2,
          'line-color': dark ? '#4c6559' : '#bbcdc0',
          'target-arrow-color': dark ? '#4c6559' : '#bbcdc0',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          label: 'data(label)',
          'font-size': 9,
          color: dark ? '#a9beb1' : '#6c8172',
          'text-rotation': 'autorotate',
          'text-background-color': dark ? '#1b2421' : '#ffffff',
          'text-background-opacity': 0.9,
          'text-background-padding': '3px',
        },
      },
      { selector: '.candidate', style: { 'line-style': 'dashed' } },
      {
        selector: '.disabled',
        style: {
          opacity: 0.3,
          'background-color': '#999999',
          'line-color': '#999999',
          'target-arrow-color': '#999999',
        },
      },
      {
        selector: ':selected',
        style: { 'border-color': dark ? '#bcf2db' : '#25634d', 'border-width': 3 },
      },
    ],
    layout: {
      name: 'cose',
      animate: false,
      padding: 55,
      nodeRepulsion: () => 12000,
      idealEdgeLength: () => 140,
    },
    minZoom: 0.2,
    maxZoom: 3,
    wheelSensitivity: 0.15,
  });
  cy.on('tap', 'node', (event) => {
    selected.value = graph.value.nodes.find((n) => n.id === event.target.id()) || null;
    detailOpen.value = true;
  });
  cy.on('tap', 'edge', (event) => {
    selected.value = graph.value.edges.find((n) => n.id === event.target.id()) || null;
    detailOpen.value = true;
  });
  observer?.disconnect();
  observer = new ResizeObserver(() => cy?.resize());
  observer.observe(container.value);
}
watch([filteredNodes, filteredEdges, mode, () => app.dark], renderGraph);
onMounted(async () => {
  await run(async () => {
    sources.value = await get('/sources');
  });
  await renderGraph();
});
onUnmounted(() => {
  cy?.destroy();
  observer?.disconnect();
});
function edit(edge: Entity | null) {
  editing.value = edge;
  fromId.value = edge?.data.from_id || null;
  toId.value = edge?.data.to_id || null;
  relationType.value = edge?.data.type || 'support';
  relationEvidence.value = edge?.data.evidence || '';
  editOpen.value = true;
}
async function save() {
  if (!fromId.value || !toId.value || !relationEvidence.value.trim()) {
    message.warning('请选择知识卡，并说明关系依据');
    return;
  }
  await run(async () => {
    const data = {
      from_id: fromId.value,
      to_id: toId.value,
      type: relationType.value,
      evidence: relationEvidence.value,
      review_status: 'confirmed',
    };
    if (editing.value)
      await patch('/graph/relations/' + editing.value.id, { data, status: 'active' });
    else await post('/graph/relations', { title: typeLabels[relationType.value], data });
    editOpen.value = false;
    detailOpen.value = false;
    await reload();
  }, '关系已保存并标记为用户确认');
}
async function approve(edge: Entity) {
  await run(async () => {
    await patch('/graph/relations/' + edge.id, {
      data: { review_status: 'confirmed' },
      status: 'active',
    });
    await reload();
    detailOpen.value = false;
  }, '关系已确认');
}
async function disable(edge: Entity) {
  await run(async () => {
    await patch('/graph/relations/' + edge.id, {
      status: 'disabled',
      data: { review_status: 'rejected' },
    });
    await reload();
    detailOpen.value = false;
  }, '关系已停用并保留记录');
}
async function generate() {
  if (!generateSources.value.length) {
    message.warning('请选择资料范围');
    return;
  }
  await run(async () => {
    const job = await post('/graph/generate', {
      source_ids: generateSources.value,
      request_id: requestId(),
    });
    generateOpen.value = false;
    await router.push('/jobs?selected=' + job.id);
  }, '关系提取任务已提交');
}
</script>
<template>
  <PageHeader
    eyebrow="CONNECTIONS WITH EVIDENCE"
    title="知识图谱"
    description="看见概念之间的支持、限制与分歧。每一条关系，都应该有依据。"
  >
    <n-button @click="edit(null)">
      <Plus :size="15" />
      添加关系
    </n-button>
    <n-button
      type="primary"
      @click="
        generateSources = sourceId ? [sourceId] : [];
        generateOpen = true;
      "
    >
      <Sparkles :size="15" />
      提取关系候选
    </n-button>
  </PageHeader>
  <div class="toolbar">
    <n-select
      v-model:value="sourceId"
      :options="sources.map((s) => ({ label: s.title, value: s.id }))"
      clearable
      placeholder="全部资料"
      style="width: 230px"
    />
    <n-select
      v-model:value="kind"
      :options="
        ['concept', 'claim', 'method', 'boundary'].map((t) => ({ label: typeLabels[t], value: t }))
      "
      clearable
      placeholder="全部节点类型"
      style="width: 170px"
    />
    <span class="muted small">
      {{ filteredNodes.length }} 个节点 · {{ filteredEdges.length }} 条关系
    </span>
    <n-radio-group v-model:value="mode" size="small" style="margin-left: auto">
      <n-radio-button value="graph">图谱</n-radio-button>
      <n-radio-button value="list">列表</n-radio-button>
    </n-radio-group>
  </div>
  <ResourceState
    :loading="loading"
    :error="error"
    :empty="!graph.nodes.length"
    title="还没有可连接的知识"
    description="蒸馏资料生成知识卡后，可以提取关系候选，也可以手动说明两个概念之间的关系。"
    @retry="reload()"
  >
    <template #icon><Network :size="36" :stroke-width="1.3" /></template>
    <div v-if="mode === 'graph'" class="graph-surface surface">
      <div class="graph-tools">
        <div class="graph-legend">
          <span>
            <i />
            概念 / 观点
          </span>
          <span>
            <i class="method" />
            方法
          </span>
          <span>
            <i class="boundary" />
            边界
          </span>
          <span class="muted">虚线：待核对 · 灰色：不可用</span>
        </div>
        <n-button size="small" @click="cy?.fit(undefined, 55)">
          <Expand :size="13" />
          适应视图
        </n-button>
      </div>
      <div
        ref="container"
        class="graph-canvas"
        role="img"
        aria-label="知识关系图。可切换列表视图使用键盘浏览。"
      />
      <p class="graph-hint">点击节点或关系查看详情；滚轮缩放，拖动移动。相似名称不会自动合并。</p>
    </div>
    <div v-else class="surface table-scroll">
      <table class="plain-table">
        <thead>
          <tr>
            <th>来源知识</th>
            <th>关系</th>
            <th>目标知识</th>
            <th>状态</th>
            <th>依据</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="e in filteredEdges"
            :key="e.id"
            :class="{ 'disabled-asset': e.status === 'disabled' }"
          >
            <td>{{ nodeName(e.data.from_id) }}</td>
            <td>{{ typeLabels[e.data.type] }}</td>
            <td>{{ nodeName(e.data.to_id) }}</td>
            <td><StatusBadge :status="e.status" /></td>
            <td>{{ textOf(e.data.evidence).slice(0, 120) }}</td>
            <td>
              <n-button
                text
                size="small"
                @click="
                  selected = e;
                  detailOpen = true;
                "
              >
                核对
              </n-button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!filteredEdges.length" class="panel-pad muted">
        当前范围尚无关系。可选择资料提取候选，或添加有依据的关系。
      </div>
    </div>
  </ResourceState>
  <n-modal v-model:show="generateOpen" preset="card" title="提取关系候选" style="width: 620px">
    <n-form-item label="明确选择分析范围">
      <n-select
        v-model:value="generateSources"
        multiple
        filterable
        :options="sources.map((s) => ({ label: s.title, value: s.id }))"
      />
    </n-form-item>
    <n-alert type="info" :show-icon="false">
      选择多份资料可比较跨书关系。模型只提出候选，不自动合并同名概念，也不把相似视为同义。此操作会调用模型。
    </n-alert>
    <div class="modal-footer">
      <n-button @click="generateOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="generate">生成候选</n-button>
    </div>
  </n-modal>
  <n-modal
    v-model:show="editOpen"
    preset="card"
    :title="editing ? '编辑与修复关系' : '添加知识关系'"
    style="width: 650px"
  >
    <n-form>
      <n-form-item label="起点知识卡">
        <n-select
          v-model:value="fromId"
          filterable
          :options="
            graph.nodes
              .filter((n) => n.kind === 'card' && n.status !== 'disabled')
              .map((n) => ({ label: n.title, value: n.id }))
          "
        />
      </n-form-item>
      <n-form-item label="关系类型">
        <n-select v-model:value="relationType" :options="relationOptions" />
      </n-form-item>
      <n-form-item label="目标知识卡">
        <n-select
          v-model:value="toId"
          filterable
          :options="
            graph.nodes
              .filter((n) => n.kind === 'card' && n.status !== 'disabled' && n.id !== fromId)
              .map((n) => ({ label: n.title, value: n.id }))
          "
        />
      </n-form-item>
      <n-form-item label="关系依据与前提">
        <n-input
          v-model:value="relationEvidence"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 10 }"
        />
      </n-form-item>
    </n-form>
    <div class="modal-footer">
      <n-button @click="editOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="save">保存并确认</n-button>
    </div>
  </n-modal>
  <n-drawer v-model:show="detailOpen" :width="520">
    <n-drawer-content
      :title="selected?.kind === 'relation' ? '关系与依据' : selected?.title"
      closable
    >
      <template v-if="selected">
        <StatusBadge :status="selected.status" />
        <n-alert v-if="selected.status === 'disabled'" type="warning" style="margin: 16px 0">
          关联来源已失效，当前内容只保留记录，不参与知识检索与生成。
        </n-alert>
        <template v-if="selected.kind === 'relation'">
          <h2 style="margin-top: 20px">{{ nodeName(selected.data.from_id) }}</h2>
          <p class="relation-direction">{{ typeLabels[selected.data.type] }} ↓</p>
          <h2>{{ nodeName(selected.data.to_id) }}</h2>
          <h3 style="margin-top: 28px">关系依据</h3>
          <MarkdownText :text="textOf(selected.data.evidence)" style="margin-top: 12px" />
          <div class="inline-actions section-spaced">
            <n-button
              type="primary"
              v-if="selected.status === 'candidate'"
              @click="approve(selected)"
            >
              <Check :size="13" />
              确认关系
            </n-button>
            <n-button @click="edit(selected)">
              {{ selected.status === 'disabled' ? '修复关系' : '编辑' }}
            </n-button>
            <n-button v-if="selected.status !== 'disabled'" @click="disable(selected)">
              不采用，保留记录
            </n-button>
          </div>
        </template>
        <template v-else>
          <p class="eyebrow" style="margin-top: 20px">
            {{ typeLabels[selected.data.type] || '知识节点' }}
          </p>
          <MarkdownText :text="textOf(selected.data.content) || '原知识已删除，仅保留节点名称。'" />
          <div class="chip-row section-spaced">
            <n-button
              v-for="(r, i) in selected.data.references || []"
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
        </template>
      </template>
    </n-drawer-content>
  </n-drawer>
  <EvidenceDrawer v-model:show="evidenceOpen" :reference="evidence" />
</template>
<style scoped>
.graph-surface {
  position: relative;
  overflow: hidden;
}
.graph-tools {
  padding: 18px 22px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  border-bottom: 1px solid var(--border);
}
.graph-legend {
  display: flex;
  align-items: center;
  gap: 20px;
  font-size: 10px;
  flex-wrap: wrap;
}
.graph-legend > span {
  display: flex;
  align-items: center;
  gap: 6px;
}
.graph-legend i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #97bca5;
  display: inline-block;
}
.graph-legend i.method {
  background: #d6bd85;
  border-radius: 2px;
}
.graph-legend i.boundary {
  background: #b896b1;
  border-radius: 0;
  transform: rotate(45deg);
}
.graph-canvas {
  height: calc(100vh - 350px);
  min-height: 450px;
  background-image: radial-gradient(var(--border) 1px, transparent 1px);
  background-size: 22px 22px;
}
.graph-hint {
  font-size: 10px;
  color: var(--muted);
  padding: 12px 22px;
  border-top: 1px solid var(--border);
}
.relation-direction {
  font-size: 13px;
  color: var(--accent);
  margin: 16px 0;
}
</style>
