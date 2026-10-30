<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Plus, Sparkles, Trash2, ArrowUp, ArrowDown } from 'lucide-vue-next';
import { get, post, patch, remove } from '../../lib/api';
import { useAction, useConfirm } from '../../lib/useData';
import { type Entity, textOf, requestId } from '../../lib/types';
import { jobPath } from '../../lib/navigation';
const emit = defineEmits(['changed']);
const route = useRoute(),
  router = useRouter();
const { busy, run, message } = useAction();
const confirm = useConfirm();
const allCards = ref<Entity[]>([]);
const cards = ref<Entity[]>([]),
  selected = ref<Entity | null>(null);
const editOpen = ref(false),
  generateOpen = ref(false),
  distillationId = ref<string | null>(null);
const title = ref(''),
  description = ref(''),
  limitations = ref(''),
  inputNames = ref(''),
  completionCriteria = ref('');
const steps = ref<{ title: string; instruction: string; output: string }[]>([]),
  cardIds = ref<string[]>([]),
  purpose = ref('');
onMounted(
  () =>
    void run(async () => {
      allCards.value = await get('/cards');
      cards.value = allCards.value.filter((c) => c.status !== 'disabled');
      if (route.query.distillation) {
        const result = await get<Entity & { cards: Entity[] }>(
          '/distillations/' + route.query.distillation,
        );
        if (
          result.status !== 'completed' ||
          (route.query.source && route.query.source !== result.data.source_id)
        )
          throw new Error('蒸馏结果不可用于生成，请核对状态与来源');
        distillationId.value = result.id;
        cards.value = result.cards.filter((c) => c.status !== 'disabled');
        cardIds.value = cards.value.map((c) => c.id);
        purpose.value = result.data.prompt || '';
        generateOpen.value = true;
      }
    }),
);
function edit(skill: Entity | null) {
  distillationId.value = null;
  cards.value = allCards.value.filter(
    (c) => c.status !== 'disabled' || skill?.data.card_ids?.includes(c.id),
  );
  selected.value = skill;
  title.value = skill?.title || '';
  description.value = textOf(skill?.data.description);
  limitations.value = textOf(skill?.data.limitations);
  completionCriteria.value = textOf(skill?.data.completion_criteria);
  inputNames.value = (skill?.data.inputs || []).map(textOf).join('\n');
  steps.value = JSON.parse(
    JSON.stringify(skill?.data.steps || [{ title: '第一步', instruction: '', output: '' }]),
  );
  cardIds.value = [...(skill?.data.card_ids || [])];
  editOpen.value = true;
}
async function save() {
  if (!title.value.trim() || !cardIds.value.length) {
    message.warning('请填写名称并绑定方法知识卡');
    return;
  }
  await run(async () => {
    const chosen = cards.value.filter((c) => cardIds.value.includes(c.id));
    const data = {
      ...(selected.value?.data || {}),
      description: description.value,
      limitations: limitations.value,
      completion_criteria: completionCriteria.value,
      inputs: inputNames.value
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
      steps: steps.value,
      card_ids: cardIds.value,
      source_ids: [...new Set(chosen.flatMap((c) => c.data.source_ids || []))],
    };
    if (selected.value)
      await patch('/skills/' + selected.value.id, { title: title.value, data, status: 'active' });
    else await post('/skills', { title: title.value, data });
    editOpen.value = false;
    emit('changed');
  }, '实践方法已保存');
}
async function generate() {
  if (!cardIds.value.length) {
    message.warning('请至少选择一张方法卡');
    return;
  }
  await run(async () => {
    const job = await post('/skills/generate', {
      card_ids: cardIds.value,
      ...(distillationId.value ? { distillation_id: distillationId.value } : {}),
      purpose: purpose.value,
      request_id: requestId(),
    });
    generateOpen.value = false;
    await router.push(jobPath(job.id));
  }, 'Skill 生成任务已提交');
}
async function del(skill: Entity) {
  await confirm('删除实践方法', '未完成的实践将停用，已有实践记录保留。原知识卡不会删除。', () =>
    run(async () => {
      await remove('/skills/' + skill.id);
      emit('changed');
    }, '方法已删除'),
  );
}
function moveStep(index: number, direction: number) {
  const next = index + direction;
  if (next < 0 || next >= steps.value.length) return;
  const copy = [...steps.value];
  [copy[index], copy[next]] = [copy[next], copy[index]];
  steps.value = copy;
}

defineExpose({ edit, del });
</script>
<template>
  <div class="inline-actions">
    <n-button @click="edit(null)">
      <Plus :size="16" />
      手动创建
    </n-button>
    <n-button type="primary" @click="generateOpen = true">
      <Sparkles :size="16" />
      从方法卡生成
    </n-button>
  </div>
  <n-modal
    v-model:show="generateOpen"
    preset="card"
    title="从方法知识卡生成 Skill"
    style="width: 650px"
  >
    <n-form>
      <n-form-item label="方法知识卡">
        <n-select
          v-model:value="cardIds"
          multiple
          filterable
          :options="cards.map((c) => ({ label: c.title, value: c.id }))"
          placeholder="选择有步骤和适用条件的方法卡"
        />
      </n-form-item>
      <n-form-item label="实践目标">
        <n-input
          v-model:value="purpose"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 6 }"
          placeholder="希望这个方法帮助你完成什么？"
        />
      </n-form-item>
    </n-form>
    <HelpTip label="Skill 生成说明">
      生成会调用管理员配置的独立 Skill 模型，输出适用条件、所需输入、步骤产物和边界。Skill
      在产品内引导实践，不会控制电脑或自动执行外部操作。
    </HelpTip>
    <div class="modal-footer">
      <n-button @click="generateOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="generate">生成方法草稿</n-button>
    </div>
  </n-modal>
  <n-modal
    v-model:show="editOpen"
    preset="card"
    :title="selected ? '编辑实践方法' : '创建实践方法'"
    style="width: 850px"
  >
    <n-form>
      <div class="form-grid">
        <n-form-item label="名称"><n-input v-model:value="title" :maxlength="100" /></n-form-item>
      </div>
      <n-form-item label="方法知识卡">
        <n-select
          v-model:value="cardIds"
          multiple
          filterable
          :options="cards.map((c) => ({ label: c.title, value: c.id }))"
        />
      </n-form-item>
      <n-form-item label="适用问题与说明">
        <n-input v-model:value="description" type="textarea" />
      </n-form-item>
      <div class="form-grid">
        <n-form-item label="开始前需要的信息（每行一项）">
          <n-input v-model:value="inputNames" type="textarea" placeholder="当前目标&#10;现实限制" />
        </n-form-item>
        <n-form-item label="不适用情况与停止条件">
          <n-input v-model:value="limitations" type="textarea" />
        </n-form-item>
      </div>
      <n-form-item label="完成标准">
        <n-input
          v-model:value="completionCriteria"
          type="textarea"
          placeholder="哪些可观察结果代表本次方法已执行完成？"
        />
      </n-form-item>
      <div class="section-heading">
        <h3>实践步骤</h3>
        <n-button
          size="small"
          :disabled="steps.length >= 20"
          @click="steps.push({ title: '', instruction: '', output: '' })"
        >
          <Plus :size="13" />
          添加步骤
        </n-button>
      </div>
      <div v-for="(step, index) in steps" :key="index" class="step-editor">
        <div class="step-editor-head">
          <strong>步骤 {{ index + 1 }}</strong>
          <div class="inline-actions">
            <n-button
              size="tiny"
              :disabled="index === 0"
              @click="moveStep(index, -1)"
              aria-label="上移步骤"
            >
              <ArrowUp :size="12" />
            </n-button>
            <n-button
              size="tiny"
              :disabled="index === steps.length - 1"
              @click="moveStep(index, 1)"
              aria-label="下移步骤"
            >
              <ArrowDown :size="12" />
            </n-button>
            <n-button
              size="tiny"
              :disabled="steps.length <= 1"
              @click="steps.splice(index, 1)"
              aria-label="删除步骤"
            >
              <Trash2 :size="12" />
            </n-button>
          </div>
        </div>
        <n-form-item label="步骤标题"><n-input v-model:value="step.title" /></n-form-item>
        <n-form-item label="操作说明">
          <n-input v-model:value="step.instruction" type="textarea" />
        </n-form-item>
        <n-form-item label="预期产物 / 完成标准">
          <n-input v-model:value="step.output" />
        </n-form-item>
      </div>
    </n-form>
    <div class="modal-footer">
      <n-button @click="editOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="save">保存并启用</n-button>
    </div>
  </n-modal>
</template>
<style scoped>
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 22px;
}
.skill-card {
  padding: 24px;
  display: flex;
  flex-direction: column;
}
.skill-symbol {
  width: 40px;
  height: 40px;
  background: var(--accent-soft);
  color: var(--accent);
  display: grid;
  place-items: center;
  border-radius: 8px;
}
.skill-card > h2 {
  font-size: 18px;
  margin-bottom: 12px;
}
.skill-card > p {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.8;
}
.skill-meta {
  display: flex;
  gap: 14px;
  font-size: 10px;
  color: var(--muted);
  margin-top: 16px;
}
.skill-preview {
  margin: 20px 0;
}
.skill-preview > div {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 6px 0;
  font-size: 12px;
}
.skill-preview span {
  width: 19px;
  height: 19px;
  border: 1px solid var(--border);
  color: var(--muted);
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-size: 9px;
}
.skill-actions {
  border-top: 1px solid var(--border);
  padding-top: 18px;
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.practice-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  width: 100%;
}
.practice-row:hover {
  background: var(--surface-subtle);
}
.step-editor {
  padding: 20px;
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin: 16px 0;
}
.step-editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  font-size: 12px;
}
.method-step {
  display: flex;
  gap: 16px;
  margin: 24px 0;
}
.method-step > span {
  font-size: 11px;
  color: var(--accent);
  background: var(--accent-soft);
  height: 24px;
  width: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.method-step > div {
  flex: 1;
  min-width: 0;
}
.method-step h3 {
  margin-bottom: 10px;
}
.completed-step {
  padding: 24px 0;
  border-bottom: 1px solid var(--border);
}
.completed-step h3 {
  display: flex;
  gap: 8px;
  align-items: center;
}
.completed-step h3 > svg {
  color: var(--accent);
}
.practice-answer {
  white-space: pre-wrap;
  font-size: 13px;
  margin: 14px 0;
  line-height: 1.9;
}
.completed-step h4 {
  margin: 0 0 10px;
  font-weight: 500;
}
.current-step {
  padding: 24px;
  margin-top: 24px;
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  border-radius: 7px;
}
.current-step h2 {
  margin-bottom: 16px;
}
.current-step > .n-button {
  display: flex;
}
</style>
