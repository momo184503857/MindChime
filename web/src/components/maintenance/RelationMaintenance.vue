<script setup lang="ts">
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { Plus, Sparkles } from 'lucide-vue-next';
import { post, patch } from '../../lib/api';
import { useAction } from '../../lib/useData';
import { type Entity, typeLabels, requestId } from '../../lib/types';
import { jobPath } from '../../lib/navigation';
const props = defineProps<{ nodes: Entity[]; sources: Entity[]; sourceId: string | null }>();
const emit = defineEmits(['changed']);
const router = useRouter();
const { busy, run, message } = useAction();
const graph = computed(() => ({ nodes: props.nodes }));
const generateOpen = ref(false),
  generateSources = ref<string[]>([]),
  editOpen = ref(false),
  editing = ref<Entity | null>(null),
  fromId = ref<string | null>(null),
  toId = ref<string | null>(null),
  relationType = ref('support'),
  relationEvidence = ref('');
const relationOptions = ['support', 'limit', 'refute', 'apply', 'similar'].map((v) => ({
  label: typeLabels[v],
  value: v,
}));
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
    emit('changed');
  }, '关系已保存并标记为用户确认');
}
async function approve(edge: Entity) {
  await run(async () => {
    await patch('/graph/relations/' + edge.id, {
      data: { review_status: 'confirmed' },
      status: 'active',
    });
    emit('changed');
  }, '关系已确认');
}
async function disable(edge: Entity) {
  await run(async () => {
    await patch('/graph/relations/' + edge.id, {
      status: 'disabled',
      data: { review_status: 'rejected' },
    });
    emit('changed');
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
    await router.push(jobPath(job.id));
  }, '关系提取任务已提交');
}

defineExpose({ edit, approve, disable });
</script>
<template>
  <div class="inline-actions">
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
  </div>
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
</template>
