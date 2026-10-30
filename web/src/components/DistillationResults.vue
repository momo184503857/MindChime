<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { type Entity, dateText } from '../lib/types';
import { get, post } from '../lib/api';
import { useResource, useAction } from '../lib/useData';
import ResourceState from './ResourceState.vue';
import DistillationReport from './DistillationReport.vue';
import StatusBadge from './StatusBadge.vue';
const props = defineProps<{ source: Entity; management?: boolean }>();
const route = useRoute(),
  router = useRouter();
const emit = defineEmits(['changed', 'rerun']);
const {
  data: results,
  loading,
  error,
  reload,
} = useResource(() => get<Entity[]>('/distillations?source_id=' + props.source.id), [], 5000);
const { busy, run } = useAction();
const selected = ref<(Entity & { cards?: Entity[] }) | null>(null),
  open = ref(false),
  filter = ref<string | null>(null);
const detailLoading = ref(false),
  detailError = ref(''),
  selectedId = ref('');
watch(
  () => props.source.id,
  () => {
    selected.value = null;
    void reload();
  },
);
async function view(id: string) {
  selectedId.value = id;
  void router.replace({ query: { ...route.query, tab: 'distillations', result: id } });
  open.value = true;
  detailLoading.value = true;
  detailError.value = '';
  try {
    const result = await get<Entity & { cards?: Entity[] }>('/distillations/' + id);
    if (result.data.source_id !== props.source.id) throw new Error('此结果不属于当前资料');
    selected.value = result;
  } catch (e) {
    detailError.value = (e as Error).message;
  } finally {
    detailLoading.value = false;
  }
}
async function activate(result: Entity) {
  await run(async () => {
    await post(`/distillations/${result.id}/activate`);
    emit('changed');
    await reload();
  }, '已设为当前结果，已有 Agent 与会话保持原绑定');
}
watch(
  () => route.query.result,
  (id) => {
    if (id && id !== selectedId.value) void view(String(id));
  },
  { immediate: true },
);
</script>
<template>
  <section class="surface panel-pad">
    <div class="toolbar">
      <h2>蒸馏结果</h2>
      <n-button @click="reload()">刷新结果</n-button>
    </div>
    <HelpTip label="蒸馏结果说明">
      每次独立保存。设为当前结果后，新建 Agent 默认使用这份知识；已有资产不受影响。
    </HelpTip>
    <n-select
      v-model:value="filter"
      clearable
      placeholder="全部蒸馏方法"
      :options="
        Array.from(
          new Map(
            results.map((r) => [
              r.data.method_id,
              { label: r.data.method?.name || r.data.method_id, value: r.data.method_id },
            ]),
          ).values(),
        )
      "
    />
    <ResourceState
      :loading="loading"
      :error="error"
      :empty="!results.length"
      title="尚无蒸馏结果"
      description="选择章节和方法后开始蒸馏；不同方法的结果会分别保留。"
      @retry="reload()"
    >
      <div
        v-for="result in results.filter((r) => !filter || r.data.method_id === filter)"
        :key="result.id"
        class="result-row"
      >
        <div>
          <strong>{{ result.data.method?.name || result.data.method_id }}</strong>
          <p class="muted small">
            {{ dateText(result.created_at) }} · 方法 v{{ result.data.method_version }}
          </p>
          <span v-if="source.data.active_distillation_id === result.id" class="accent">
            当前结果
          </span>
        </div>
        <StatusBadge :status="result.status" />
        <div class="inline-actions">
          <n-button size="small" @click="view(result.id)">查看结果</n-button>
          <n-button
            v-if="management"
            size="small"
            :loading="busy"
            :disabled="
              result.status !== 'completed' || source.data.active_distillation_id === result.id
            "
            @click="activate(result)"
          >
            设为当前结果
          </n-button>
          <n-button v-if="management" size="small" @click="emit('rerun', result)">
            再次运行
          </n-button>
        </div>
      </div>
      <p v-if="filter && !results.some((r) => r.data.method_id === filter)" class="muted">
        此方法尚无结果。
      </p>
    </ResourceState>
    <n-modal
      v-model:show="open"
      @update:show="
        (value: boolean) => {
          if (!value) {
            selectedId = '';
            void router.replace({ query: { ...route.query, result: undefined } });
          }
        }
      "
      preset="card"
      title="蒸馏结果与证据"
      style="width: 1000px; max-width: calc(100vw - 48px)"
    >
      <ResourceState :loading="detailLoading" :error="detailError" @retry="view(selectedId)">
        <DistillationReport v-if="selected && !detailLoading" :result="selected" />
      </ResourceState>
    </n-modal>
  </section>
</template>
<style scoped>
.result-notice {
  margin: 12px 0 20px;
  line-height: 1.7;
}
.result-row {
  display: flex;
  align-items: center;
  gap: 16px;
  border-bottom: 1px solid var(--border);
  padding: 20px 0;
}
.result-row > div:first-child {
  flex: 1;
  min-width: 0;
}
.result-row .inline-actions {
  flex-wrap: wrap;
}
</style>
