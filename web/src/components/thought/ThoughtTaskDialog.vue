<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { get, post } from '../../lib/api';
import { type Entity, requestId } from '../../lib/types';
import { useAction } from '../../lib/useData';
const props = defineProps<{
  show: boolean;
  persons: Entity[];
  sources: Entity[];
  models: any[];
  defaultPersonId: string | null;
  defaultSourceId?: string;
}>();
const emit = defineEmits(['update:show', 'submitted']);
const taskOpen = computed({ get: () => props.show, set: (v) => emit('update:show', v) });
const personId = ref<string | null>(null),
  sourceIds = ref<string[]>([]),
  chapterIds = ref<string[]>([]),
  chapters = ref<Entity[]>([]),
  network = ref(false),
  prompt = ref(''),
  model = ref<string | null>(null);
const { busy, run, message } = useAction();
watch(
  () => props.show,
  (show) => {
    if (show) {
      personId.value = props.defaultPersonId;
      sourceIds.value = props.defaultSourceId ? [props.defaultSourceId] : [];
      chapterIds.value = [];
      chapters.value = [];
      network.value = false;
      prompt.value = '';
      model.value = null;
    }
  },
);
let loadSequence = 0;
watch(sourceIds, async (ids) => {
  const seq = ++loadSequence;
  try {
    const values = await Promise.all(ids.map((id) => get<any>('/sources/' + id)));
    if (seq !== loadSequence) return;
    chapters.value = values
      .flatMap((v) => v.chapters)
      .filter((c) => c.data.text?.trim() && c.data.selected !== false);
    chapterIds.value = chapters.value.map((c) => c.id);
  } catch (e) {
    message.error((e as Error).message);
  }
});
async function launch() {
  await run(async () => {
    const job = await post<Entity>('/distillations', {
      distillation_type: 'thought',
      method_id: 'nuwa',
      person_id: personId.value,
      source_ids: sourceIds.value,
      chapter_ids: chapterIds.value,
      allow_network: network.value,
      prompt: prompt.value,
      model_profile_id: model.value || undefined,
      request_id: requestId(),
    });
    taskOpen.value = false;
    emit('submitted', job);
  }, '女娲思想蒸馏已提交');
}
</script>
<template>
  <n-modal v-model:show="taskOpen" preset="card" title="女娲 · 思想蒸馏" style="width: 760px">
    <n-form>
      <n-form-item label="蒸馏类型"><n-tag>思想蒸馏 · 女娲</n-tag></n-form-item>
      <n-form-item label="人物">
        <n-select
          v-model:value="personId"
          :options="persons.map((p) => ({ label: p.title, value: p.id }))"
          placeholder="选择人物"
        />
      </n-form-item>
      <n-form-item label="来源资料">
        <n-select
          v-model:value="sourceIds"
          multiple
          filterable
          :options="
            sources
              .filter((s) => !['disabled', 'failed', 'file_deleted'].includes(s.status))
              .map((s) => ({ label: s.title, value: s.id }))
          "
          placeholder="可选择同一人物的多份资料"
        />
      </n-form-item>
      <n-form-item v-if="chapters.length" label="分析章节">
        <n-select
          v-model:value="chapterIds"
          multiple
          filterable
          :options="chapters.map((c) => ({ label: c.title, value: c.id }))"
        />
      </n-form-item>
      <n-form-item label="允许联网调研">
        <n-switch v-model:value="network" />
        <HelpTip label="联网调研说明">
          默认关闭。开启后可搜索并采集公开网页，最多六次搜索、二十页正文；缺少搜索服务配置时不能提交。网页保存为可追溯资料后才参与提炼。
        </HelpTip>
      </n-form-item>
      <n-form-item label="关注方向">
        <n-input
          v-model:value="prompt"
          type="textarea"
          :maxlength="5000"
          placeholder="例如决策方法、价值冲突、思想演变"
        />
      </n-form-item>
      <n-form-item label="生成模型">
        <n-select
          v-model:value="model"
          clearable
          :options="
            models
              .filter((m) => m.enabled && !m.capabilities?.embedding)
              .map((m) => ({ label: m.name, value: m.id }))
          "
          placeholder="沿用管理员配置的思想蒸馏模型"
        />
      </n-form-item>
    </n-form>
    <div class="modal-footer">
      <n-button @click="taskOpen = false">取消</n-button>
      <n-button
        type="primary"
        :loading="busy"
        :disabled="!personId || (!network && !chapterIds.length)"
        @click="launch"
      >
        提交思想蒸馏
      </n-button>
    </div>
  </n-modal>
</template>
