<script setup lang="ts">
import { computed, ref } from 'vue';
import { get, post, remove } from '../../lib/api';
import { useResource } from '../../lib/useData';
import { useAction } from '../../lib/useData';
import { type Entity } from '../../lib/types';
import PageHeader from '../../components/PageHeader.vue';
import MarkdownText from '../../components/MarkdownText.vue';
import EvidenceDrawer from '../../components/EvidenceDrawer.vue';
import ResourceState from '../../components/ResourceState.vue';
const labels: Record<string, string> = {
  source: '资料',
  card: '知识卡',
  distillation: '蒸馏结果',
  person: '人物',
  cognitive_profile: '思想画像',
  agent: '智能体',
  skill: '实践 Skill',
  relation: '图谱关系',
};
const { data, loading, error, reload } = useResource(() => get<any[]>('/publications'), [], 15000);
const { busy, run } = useAction();
const evidenceOpen = ref(false),
  evidence = ref<any>(null);
const kind = ref<string | null>(null),
  query = ref(''),
  selected = ref<Entity | null>(null),
  preview = ref<any>(null),
  open = ref(false),
  version = ref<number | null>(null),
  versions = ref<number[]>([]);
const rows = computed(() =>
  data.value.filter((r) => (!kind.value || r.kind === kind.value) && r.title.includes(query.value)),
);
async function inspect(r: Entity) {
  selected.value = r;
  version.value = r.version;
  preview.value = null;
  open.value = true;
  await run(async () => {
    versions.value = await get<number[]>('/publications/' + r.id + '/versions');
    await check();
  });
}
async function check() {
  if (selected.value) {
    selected.value = await get<Entity>(
      '/publications/' + selected.value.id + '/version-detail?version=' + version.value,
    );
    preview.value = await get(
      '/publications/' + selected.value!.id + '/preview?version=' + version.value,
    );
  }
}
async function reviewCard() {
  if (!selected.value) return;
  await run(async () => {
    await post('/reviews/' + selected.value!.id, { version: version.value, decision: 'verified' });
    await check();
  }, '已记录此版本的人工核对');
}
async function publish() {
  if (!selected.value) return;
  await run(async () => {
    await post('/publications/' + selected.value!.id + '?version=' + version.value);
    open.value = false;
    await reload();
  }, '所选资产版本已发布');
}
async function unpublish(r: Entity) {
  await run(async () => {
    await remove('/publications/' + r.id);
    await reload();
  }, '资产已下架，个人历史保留');
}
</script>
<template>
  <PageHeader
    title="发布管理"
    description="先核对并发布依赖，再发布结果、智能体和方法。后台可用不代表已向普通用户公开。"
  />
  <div class="toolbar">
    <n-input v-model:value="query" placeholder="搜索资产名称" clearable />
    <n-form-item label="资产类型" label-placement="left" style="margin-bottom: 0; min-width: 220px">
      <n-select
        v-model:value="kind"
        clearable
        placeholder="全部资产"
        :options="Object.entries(labels).map(([value, label]) => ({ value, label }))"
      />
    </n-form-item>
  </div>
  <ResourceState :loading="loading" :error="error" @retry="reload()">
    <div class="surface table-scroll">
      <table class="plain-table">
        <thead>
          <tr>
            <th>资产</th>
            <th>类型</th>
            <th>后台版本</th>
            <th>发布版本</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.title }}</td>
            <td>{{ labels[r.kind] }}</td>
            <td>v{{ r.version }}</td>
            <td>{{ r.published_version ? 'v' + r.published_version : '未发布' }}</td>
            <td>
              <div class="inline-actions">
                <n-button size="small" @click="inspect(r)">检查并发布</n-button>
                <n-button v-if="r.published_version" size="small" @click="unpublish(r)">
                  下架
                </n-button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="panel-pad muted">没有匹配的资产。</p>
    </div>
  </ResourceState>
  <n-modal v-model:show="open" preset="card" title="检查发布版本" style="width: 600px">
    <h3>{{ selected?.title }}</h3>
    <n-form-item label="发布版本">
      <n-select
        v-model:value="version"
        :options="versions.map((v) => ({ label: 'v' + v, value: v }))"
        @update:value="check"
      />
    </n-form-item>
    <section v-if="selected?.kind === 'card'" class="surface panel-pad">
      <MarkdownText :text="selected.data.content" />
      <div class="inline-actions">
        <n-button
          v-for="(ref, index) in selected.data.references || []"
          :key="index"
          size="small"
          @click="
            evidence = ref;
            evidenceOpen = true;
          "
        >
          核对原文 {{ Number(index) + 1 }}
        </n-button>
        <n-button :loading="busy" @click="reviewCard">确认此卡片版本已核对</n-button>
      </div>
    </section>
    <p class="muted">只有明确发布的版本对普通用户可见；不会自动发布依赖。</p>
    <ul v-if="preview?.blockers?.length">
      <li v-for="b in preview.blockers" :key="b">{{ b }}</li>
    </ul>
    <p v-else-if="preview?.ready">依赖与审核检查通过，可以发布此版本。</p>
    <div class="modal-footer">
      <n-button @click="open = false">取消</n-button>
      <n-button type="primary" :disabled="!preview?.ready" :loading="busy" @click="publish">
        发布此版本
      </n-button>
    </div>
  </n-modal>
  <EvidenceDrawer v-model:show="evidenceOpen" :reference="evidence" />
</template>
