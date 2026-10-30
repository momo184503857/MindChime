<script setup lang="ts">
import { isAdmin } from '../../lib/auth';
import { ref, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, download } from '../../lib/api';
import { useResource, useAction } from '../../lib/useData';
import { type Entity, textOf } from '../../lib/types';
import PageHeader from '../../components/PageHeader.vue';
import ResourceState from '../../components/ResourceState.vue';
import StatusBadge from '../../components/StatusBadge.vue';
import AgentFacts from '../../components/AgentFacts.vue';
const route = useRoute(),
  router = useRouter();
const { data, loading, error, reload } = useResource(
  async () => {
    const [agents, sources] = await Promise.all([
      get<Entity[]>('/agents'),
      get<Entity[]>('/sources'),
    ]);
    return { agents, sources };
  },
  { agents: [], sources: [] },
  10000,
);
const query = ref(''),
  compared = ref<string[]>([]),
  compare = ref(false),
  detailOpen = ref(false),
  detail = ref<any>(null),
  detailError = ref(''),
  detailLoading = ref(false);
const available = (agent: Entity) => ['active', 'ready', 'available'].includes(agent.status);
const agents = computed(() =>
  data.value.agents.filter(
    (a) => available(a) && `${a.title} ${a.data.purpose || ''}`.includes(query.value),
  ),
);
const comparison = computed(() => data.value.agents.filter((a) => compared.value.includes(a.id)));
const { busy, run } = useAction();
async function view(id: string) {
  detailOpen.value = true;
  detailLoading.value = true;
  detailError.value = '';
  detail.value = null;
  try {
    detail.value = await get('/agents/' + id);
  } catch (e) {
    detailError.value = (e as Error).message;
  } finally {
    detailLoading.value = false;
  }
}
function select(id: string) {
  void router.push({ query: { ...route.query, selected: id } });
}
watch(
  () => route.query.selected,
  (id) => {
    if (id) void view(String(id));
    else detailOpen.value = false;
  },
  { immediate: true },
);
async function chat(agent: Entity) {
  if (!available(agent)) return;
  await run(async () => {
    const c = await post<Entity>('/conversations', {
      title: '与' + agent.title + '的对话',
      data: { mode: 'single', agent_ids: [agent.id] },
    });
    await router.push('/chat/' + c.id);
  });
}
</script>
<template>
  <PageHeader title="思想智能体" description="选择合适的知识与视角，围绕你的问题展开对话。">
    <n-button v-if="isAdmin" @click="router.push('/admin/agents')">管理智能体</n-button>
  </PageHeader>
  <div class="toolbar">
    <n-input v-model:value="query" class="search-field" placeholder="搜索名称或用途" clearable />
    <n-button @click="compare = !compare">{{ compare ? '退出比较' : '比较不同视角' }}</n-button>
  </div>
  <ResourceState
    :loading="loading"
    :error="error"
    :empty="!agents.length"
    title="还没有可用的思想智能体"
    description="管理员发布智能体后，你就可以在这里选择并开始对话。"
    @retry="reload()"
  >
    <template #action>
      <n-button v-if="isAdmin" @click="router.push('/admin/agents')">去后台创建智能体</n-button>
    </template>
    <div class="agent-gallery">
      <article v-for="agent in agents" :key="agent.id" class="surface panel-pad">
        <div class="section-heading">
          <h2>
            <button class="agent-title" @click="select(agent.id)">{{ agent.title }}</button>
          </h2>
          <n-checkbox
            v-if="compare"
            :aria-label="'比较' + agent.title"
            :checked="compared.includes(agent.id)"
            :disabled="!compared.includes(agent.id) && compared.length >= 3"
            @update:checked="
              compared = $event ? [...compared, agent.id] : compared.filter((id) => id !== agent.id)
            "
          />
        </div>
        <StatusBadge :status="agent.status" />
        <p class="muted">{{ agent.data.purpose || '尚未填写用途' }}</p>
        <p>{{ textOf(agent.data.perspective) }}</p>
        <p class="muted small">
          {{ agent.data.source_ids?.length || 0 }} 份来源 · v{{ agent.version }}
        </p>
        <div class="inline-actions">
          <n-button type="primary" :loading="busy" @click="chat(agent)">开始对话</n-button>
          <n-button @click="select(agent.id)">查看详情</n-button>
        </div>
      </article>
    </div>
    <section
      v-if="compare && comparison.length >= 2"
      class="surface panel-pad section-spaced table-scroll"
    >
      <table class="plain-table">
        <thead>
          <tr>
            <th>比较维度</th>
            <th v-for="a in comparison" :key="a.id">{{ a.title }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="field in [
              { key: 'purpose', label: '用途' },
              { key: 'perspective', label: '视角' },
              { key: 'framework', label: '框架' },
              { key: 'boundaries', label: '边界' },
            ]"
            :key="field.key"
          >
            <th>{{ field.label }}</th>
            <td v-for="a in comparison" :key="a.id">{{ textOf(a.data[field.key]) || '未填写' }}</td>
          </tr>
          <tr>
            <th>共同来源</th>
            <td v-for="a in comparison" :key="a.id">
              {{
                (a.data.source_ids || [])
                  .map((id: string) => data.sources.find((s) => s.id === id)?.title || '来源已失效')
                  .join('、')
              }}
            </td>
          </tr>
        </tbody>
      </table>
      <HelpTip label="使用说明">
        相同来源表示共同证据，多个智能体同意一个观点不等于多个独立来源已验证。
      </HelpTip>
    </section>
  </ResourceState>
  <n-drawer
    :show="detailOpen"
    @update:show="
      (value: boolean) => {
        if (!value) void router.replace({ query: { ...route.query, selected: undefined } });
      }
    "
    :width="600"
  >
    <n-drawer-content :title="detail?.agent?.title || '智能体详情'" closable>
      <ResourceState
        :loading="detailLoading"
        :error="detailError"
        @retry="view(String(route.query.selected))"
      >
        <template v-if="detail?.agent">
          <StatusBadge :status="detail.agent.status" />
          <AgentFacts :agent="detail.agent" :knowledge="detail.knowledge_summary" />
          <div class="inline-actions section-spaced">
            <n-button
              type="primary"
              :disabled="!available(detail.agent)"
              @click="chat(detail.agent)"
            >
              开始对话
            </n-button>
            <n-button v-if="isAdmin"
              @click="router.push({ path: '/admin/agents', query: { selected: detail.agent.id } })"
            >
              维护此智能体
            </n-button>
            <n-button v-if="isAdmin"
              @click="run(() => download(`/export?kind=agent&id=${detail.agent.id}&format=zip`))"
            >
              导出便携包
            </n-button>
          </div>
        </template>
      </ResourceState>
    </n-drawer-content>
  </n-drawer>
</template>
<style scoped>
.agent-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 22px;
}
.agent-gallery p {
  margin: 16px 0;
  line-height: 1.7;
}
.agent-title {
  font: inherit;
  color: inherit;
  border: 0;
  background: none;
  padding: 0;
  text-align: left;
  cursor: pointer;
}
</style>
