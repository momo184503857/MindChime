<script setup lang="ts">
import { isAdmin } from '../lib/auth';
import { switchArea } from '../lib/navigation';
import { ref, watch, computed, onMounted, onUnmounted, nextTick } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { defineAsyncComponent } from 'vue';
const RelationMaintenance = defineAsyncComponent(
  () => import('../components/maintenance/RelationMaintenance.vue'),
);
const props = defineProps<{ management?: boolean }>();
const maintenance = ref<InstanceType<typeof RelationMaintenance> | null>(null);
const route = useRoute();
import cytoscape from 'cytoscape';
import { Network, Expand, Check, Quote } from 'lucide-vue-next';
import { get } from '../lib/api';
import { useResource, useAction } from '../lib/useData';
import { type Entity, type Reference, typeLabels, textOf } from '../lib/types';
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
const { run } = useAction();
const sources = ref<Entity[]>([]);
const sourceId = ref<string | null>(String(route.query.source_id || '') || null),
  mode = ref(String(route.query.mode || 'graph')),
  kind = ref<string | null>(null),
  container = ref<HTMLElement | null>(null),
  selected = ref<Entity | null>(null),
  detailOpen = ref(false);
const evidence = ref<Reference | null>(null),
  evidenceOpen = ref(false);
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
    void router.push({ query: { ...route.query, selected: event.target.id() } });
  });
  cy.on('tap', 'edge', (event) => {
    void router.push({ query: { ...route.query, selected: event.target.id() } });
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
watch([sourceId, mode], () => {
  void router.replace({
    query: { ...route.query, source_id: sourceId.value || undefined, mode: mode.value },
  });
});
watch(
  [graph, () => route.query.selected],
  () => {
    selected.value =
      [...graph.value.nodes, ...graph.value.edges].find((e) => e.id === route.query.selected) ||
      null;
    detailOpen.value = !!selected.value;
  },
  { immediate: true },
);
watch(
  () => route.query,
  (query) => {
    sourceId.value = String(query.source_id || '') || null;
    mode.value = String(query.mode || 'graph');
  },
);
</script>
<template>
  <PageHeader
    eyebrow="CONNECTIONS WITH EVIDENCE"
    :title="management ? '关系审核' : '知识图谱'"
    description="看见概念之间的支持、限制与分歧。每一条关系，都应该有依据。"
  >
    <RelationMaintenance
      v-if="management"
      ref="maintenance"
      :nodes="graph.nodes"
      :sources="sources"
      :source-id="sourceId"
      @changed="
        reload(true);
        detailOpen = false;
        router.replace({ query: { ...route.query, selected: undefined } });
      "
    />
    <n-button v-if="isAdmin" @click="router.push(switchArea(route, management ? 'front' : 'admin'))">
      {{ management ? '前台查看' : '管理关系' }}
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
          <HelpTip label="图谱状态说明" text="虚线表示待核对关系，灰色表示不可用资产。" />
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
      <HelpTip label="使用说明">
        点击节点或关系查看详情；滚轮缩放，拖动移动。相似名称不会自动合并。
      </HelpTip>
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
                @click="router.push({ query: { ...route.query, selected: e.id } })"
              >
                查看依据
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
  <n-drawer
    v-model:show="detailOpen"
    @update:show="
      (value: boolean) => {
        if (!value) void router.replace({ query: { ...route.query, selected: undefined } });
      }
    "
    :width="520"
  >
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
          <n-button
            v-if="isAdmin && (!management)"
            class="section-spaced"
            @click="router.push({ path: '/admin/graph', query: route.query })"
          >
            管理此关系
          </n-button>
          <div v-if="management" class="inline-actions section-spaced">
            <n-button
              type="primary"
              v-if="selected.status === 'candidate'"
              @click="maintenance?.approve(selected)"
            >
              <Check :size="13" />
              确认关系
            </n-button>
            <n-button @click="maintenance?.edit(selected)">
              {{ selected.status === 'disabled' ? '修复关系' : '编辑' }}
            </n-button>
            <n-button v-if="selected.status !== 'disabled'" @click="maintenance?.disable(selected)">
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
