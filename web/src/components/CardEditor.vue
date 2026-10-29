<script setup lang="ts">
import { ref, watch } from 'vue';
import { type Entity, textOf } from '../lib/types';
import { post, patch } from '../lib/api';
import { useAction } from '../lib/useData';
const props = defineProps<{ show: boolean; card: Entity | null; sourceId?: string }>();
const emit = defineEmits(['update:show', 'saved']);
const { busy, run, message } = useAction();
const title = ref(''),
  type = ref('concept'),
  content = ref(''),
  applicability = ref(''),
  limitations = ref(''),
  review = ref('pending');
watch(
  () => [props.show, props.card],
  () => {
    if (!props.show) return;
    title.value = props.card?.title || '';
    type.value = props.card?.data.type || 'concept';
    content.value = textOf(props.card?.data.content);
    applicability.value = textOf(props.card?.data.applicability);
    limitations.value = textOf(props.card?.data.limitations);
    review.value = props.card?.data.review_status || 'pending';
  },
  { immediate: true },
);
async function save() {
  if (!title.value.trim() || !content.value.trim()) {
    message.warning('请填写标题和知识内容');
    return;
  }
  await run(async () => {
    const data = {
      ...(props.card?.data || {}),
      type: type.value,
      content: content.value,
      applicability: applicability.value,
      limitations: limitations.value,
      review_status: review.value,
      edit_origin: props.card ? 'user_modified' : 'user_original',
      ...(!props.card
        ? {
            source_ids: props.sourceId ? [props.sourceId] : [],
            attribution: '用户补充',
            references: [],
          }
        : {}),
    };
    if (props.card) await patch('/cards/' + props.card.id, { title: title.value, data });
    else await post('/cards', { title: title.value, data });
    emit('saved');
    emit('update:show', false);
  }, '知识卡已保存为新版本');
}
</script>
<template>
  <n-modal
    :show="show"
    @update:show="emit('update:show', $event)"
    preset="card"
    :title="card ? '编辑知识卡' : '添加个人知识卡'"
    style="width: 700px"
  >
    <n-form label-placement="top">
      <div class="form-grid">
        <n-form-item label="标题"><n-input v-model:value="title" :maxlength="100" /></n-form-item>
        <n-form-item label="类型">
          <n-select
            v-model:value="type"
            :options="[
              { label: '概念', value: 'concept' },
              { label: '观点', value: 'claim' },
              { label: '方法', value: 'method' },
              { label: '边界', value: 'boundary' },
            ]"
          />
        </n-form-item>
      </div>
      <n-form-item label="核心内容">
        <n-input v-model:value="content" type="textarea" :autosize="{ minRows: 4, maxRows: 12 }" />
      </n-form-item>
      <n-form-item label="适用场景与前提">
        <n-input
          v-model:value="applicability"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
        />
      </n-form-item>
      <n-form-item label="局限与争议">
        <n-input
          v-model:value="limitations"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
        />
      </n-form-item>
      <n-form-item label="核对状态">
        <n-select
          v-model:value="review"
          :options="[
            { label: '待核对', value: 'pending' },
            { label: '用户已核对', value: 'verified' },
            { label: '存在疑问', value: 'questionable' },
          ]"
        />
      </n-form-item>
    </n-form>
    <n-alert type="info" :show-icon="false">
      修改会保留用户编辑标记。原引用仍可核对，但不代表修改后的全部表述均来自原书。
    </n-alert>
    <div class="modal-footer">
      <n-button @click="emit('update:show', false)">取消</n-button>
      <n-button type="primary" :loading="busy" @click="save">保存版本</n-button>
    </div>
  </n-modal>
</template>
