<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import { get, post, patch } from '../lib/api';
import { type Entity, type Profile, textOf, requestId } from '../lib/types';
import { useAction } from '../lib/useData';
const props = defineProps<{
  show: boolean;
  agent?: Entity | null;
  sourceId?: string;
  generate?: boolean;
}>();
const emit = defineEmits(['update:show', 'saved', 'job']);
const { busy, run, message } = useAction();
const sources = ref<Entity[]>([]),
  cards = ref<Entity[]>([]),
  chapters = ref<Entity[]>([]),
  profiles = ref<Profile[]>([]);
const sourceDetails = ref<Record<string, any>>({});
const sourceVersions = ref<Record<string, number>>({});
const title = ref(''),
  purpose = ref(''),
  perspective = ref(''),
  framework = ref(''),
  methods = ref(''),
  boundaries = ref(''),
  style = ref('clear'),
  sourceIds = ref<string[]>([]),
  chapterIds = ref<string[]>([]),
  cardIds = ref<string[]>([]),
  excluded = ref<string[]>([]),
  model = ref<string | null>(null),
  general = ref(false),
  count = ref(1),
  step = ref('knowledge');
const matchingCards = computed(() =>
  cards.value.filter(
    (c) =>
      !sourceIds.value.length ||
      (c.data.source_ids || []).some((id: string) => sourceIds.value.includes(id)),
  ),
);
const unreviewed = computed(
  () =>
    matchingCards.value.filter(
      (c) =>
        (!cardIds.value.length || cardIds.value.includes(c.id)) &&
        !['reviewed', 'verified'].includes(c.data.review_status),
    ).length,
);
watch(
  () => props.show,
  async (show) => {
    if (!show) return;
    const a = props.agent;
    title.value = a?.title || '';
    purpose.value = a?.data.purpose || '';
    perspective.value = textOf(a?.data.perspective);
    framework.value = textOf(a?.data.framework);
    methods.value = textOf(a?.data.methods);
    boundaries.value = textOf(a?.data.boundaries);
    sourceVersions.value = { ...(a?.data.source_versions || {}) };
    sourceIds.value = a?.data.source_ids || (props.sourceId ? [props.sourceId] : []);
    chapterIds.value = a?.data.chapter_ids || [];
    cardIds.value = a?.data.card_ids || [];
    excluded.value = a?.data.excluded_card_ids || [];
    model.value = a?.data.model_profile_id || null;
    general.value = !!a?.data.general_knowledge;
    style.value = a?.data.style || 'clear';
    step.value = 'knowledge';
    await run(async () => {
      [sources.value, cards.value, profiles.value] = await Promise.all([
        get('/sources'),
        get('/cards'),
        get('/profiles'),
      ]);
      await loadChapters();
    });
  },
);
async function loadChapters() {
  const details = await Promise.all(
    sourceIds.value.map(async (id) => {
      const current = await get<any>('/sources/' + id);
      sourceDetails.value[id] = current;
      if (!sourceVersions.value[id]) sourceVersions.value[id] = current.source.version;
      if (sourceVersions.value[id] !== current.source.version)
        return await get<any>(`/sources/${id}?version=${sourceVersions.value[id]}`);
      return current;
    }),
  );
  chapters.value = details.flatMap((s) => s.chapters || []);
  const selectedCards = details.flatMap((s) => s.cards || []);
  const others = cards.value.filter(
    (c) => !(c.data.source_ids || []).some((id: string) => sourceIds.value.includes(id)),
  );
  cards.value = [...others, ...selectedCards];
}
async function changeVersion() {
  chapterIds.value = [];
  cardIds.value = [];
  excluded.value = [];
  await run(loadChapters);
}
async function changeSources(ids: string[]) {
  sourceIds.value = ids;
  chapterIds.value = [];
  cardIds.value = [];
  excluded.value = [];
  await run(loadChapters);
}
async function save(status = 'draft') {
  if (!sourceIds.value.length && !cardIds.value.length) {
    message.warning('至少绑定一份资料或一张知识卡');
    return;
  }
  if (!purpose.value.trim()) {
    message.warning('请填写用途');
    return;
  }
  await run(
    async () => {
      if (props.generate) {
        const job = await post('/agents/generate', {
          source_ids: sourceIds.value,
          source_versions: sourceVersions.value,
          chapter_ids: chapterIds.value,
          card_ids: cardIds.value,
          purpose: purpose.value,
          count: count.value,
          model_profile_id: model.value || undefined,
          request_id: requestId(),
        });
        emit('job', job);
      } else {
        if (!title.value.trim()) throw new Error('请填写智能体名称');
        const data = {
          source_ids: sourceIds.value,
          source_versions: sourceVersions.value,
          chapter_ids: chapterIds.value,
          card_ids: cardIds.value,
          excluded_card_ids: excluded.value,
          purpose: purpose.value,
          perspective: perspective.value,
          framework: framework.value,
          methods: methods.value,
          boundaries: boundaries.value,
          style: style.value,
          model_profile_id: model.value,
          general_knowledge: general.value,
        };
        let entity;
        if (props.agent)
          entity = await patch('/agents/' + props.agent.id, { title: title.value, data, status });
        else {
          entity = await post('/agents', { title: title.value, data, status });
          if (status === 'active')
            entity = await patch('/agents/' + entity.id, { status: 'active' });
        }
        emit('saved', entity);
      }
      emit('update:show', false);
    },
    props.generate ? '生成任务已提交' : '智能体已保存',
  );
}
</script>
<template>
  <n-modal
    :show="show"
    @update:show="emit('update:show', $event)"
    preset="card"
    :title="generate ? '从知识生成思想智能体' : agent ? '编辑智能体 · 新版本' : '手动组合智能体'"
    style="width: 820px"
  >
    <n-tabs v-model:value="step" type="line">
      <n-tab-pane name="knowledge" tab="1 · 选择知识">
        <n-form>
          <n-form-item label="绑定资料">
            <n-select
              :value="sourceIds"
              @update:value="changeSources"
              multiple
              filterable
              :options="sources.map((s) => ({ label: s.title, value: s.id }))"
              placeholder="选择一本或多本资料"
            />
          </n-form-item>
          <div class="source-version-fields">
            <n-form-item
              v-for="sourceId in sourceIds"
              :key="sourceId"
              :label="(sources.find((s) => s.id === sourceId)?.title || '资料') + ' · 知识版本'"
            >
              <n-select
                v-model:value="sourceVersions[sourceId]"
                :options="
                  (sourceDetails[sourceId]?.versions || []).map((v: Entity) => ({
                    label: `版本 ${v.version} · ${v.data.chapter_ids?.length || 0} 个章节`,
                    value: v.version,
                  }))
                "
                @update:value="changeVersion"
              />
            </n-form-item>
          </div>
          <n-form-item label="限定章节（留空表示使用所选资料的可用蒸馏范围）">
            <n-select
              v-model:value="chapterIds"
              multiple
              filterable
              clearable
              :options="chapters.map((c) => ({ label: c.title, value: c.id }))"
            />
          </n-form-item>
          <n-form-item label="限定知识卡（可选）">
            <n-select
              v-model:value="cardIds"
              multiple
              filterable
              clearable
              :options="matchingCards.map((c) => ({ label: c.title, value: c.id }))"
            />
          </n-form-item>
          <n-form-item v-if="!generate" label="排除的知识卡及对应原文证据">
            <n-select
              v-model:value="excluded"
              multiple
              filterable
              clearable
              :options="matchingCards.map((c) => ({ label: c.title, value: c.id }))"
            />
          </n-form-item>
        </n-form>
        <n-alert type="info" :show-icon="false">
          当前范围内有
          {{ unreviewed }}
          张卡片尚未由你核对。智能体可检索绑定知识与所选范围原文，但不会读取其他私人资料。
        </n-alert>
      </n-tab-pane>
      <n-tab-pane name="purpose" tab="2 · 用途与框架">
        <n-form>
          <n-form-item v-if="!generate" label="名称">
            <n-input v-model:value="title" :maxlength="30" placeholder="清楚描述它的分析侧重" />
          </n-form-item>
          <n-form-item label="希望它帮助你做什么">
            <n-input
              v-model:value="purpose"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 6 }"
              :maxlength="5000"
              placeholder="例如：帮助我设计可逆的小步尝试，并审视适用条件。"
            />
          </n-form-item>
          <div v-if="generate">
            <n-form-item label="生成草稿数量">
              <n-input-number v-model:value="count" :min="1" :max="3" />
            </n-form-item>
            <p class="field-hint">
              多个草稿会展示不同视角；生成后需检查知识范围、框架与边界，再发布为可用智能体。
            </p>
          </div>
          <template v-else>
            <n-form-item label="分析视角">
              <n-input
                v-model:value="perspective"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 5 }"
              />
            </n-form-item>
            <n-form-item label="思考框架">
              <n-input
                v-model:value="framework"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="关注的维度、判断顺序和必要条件"
              />
            </n-form-item>
            <n-form-item label="常用方法">
              <n-input
                v-model:value="methods"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 5 }"
              />
            </n-form-item>
            <n-form-item label="边界与不适用场景">
              <n-input
                v-model:value="boundaries"
                type="textarea"
                :autosize="{
                  minRows: 2,
                  maxRows: 5,
                }"
              />
            </n-form-item>
          </template>
        </n-form>
      </n-tab-pane>
      <n-tab-pane name="settings" tab="3 · 模型与策略">
        <n-form>
          <n-form-item label="模型">
            <n-select
              v-model:value="model"
              clearable
              :options="
                profiles
                  .filter((p) => p.enabled && !p.capabilities?.embedding)
                  .map((p) => ({ label: `${p.name} · ${p.model}`, value: p.id }))
              "
              placeholder="沿用对应任务默认模型"
            />
          </n-form-item>
          <template v-if="!generate">
            <n-form-item label="表达风格">
              <n-select
                v-model:value="style"
                :options="[
                  { label: '清楚、克制', value: 'clear' },
                  { label: '简洁', value: 'concise' },
                  { label: '启发式提问', value: 'socratic' },
                  { label: '详细解释', value: 'detailed' },
                ]"
              />
            </n-form-item>
            <n-form-item label="允许一般知识补充">
              <n-switch v-model:value="general" />
              <span class="field-hint" style="margin: 0 0 0 12px">
                {{
                  general
                    ? '允许补充，并明确标记为非绑定来源'
                    : '仅依据绑定知识，资料不足时说明不知道'
                }}
              </span>
            </n-form-item>
          </template>
        </n-form>
        <n-alert type="warning" :show-icon="false">
          相关内容会发送到你选择的模型服务。模型费用由服务商收取，试聊与正式对话都会产生真实调用。
        </n-alert>
      </n-tab-pane>
    </n-tabs>
    <div class="modal-footer">
      <n-button @click="emit('update:show', false)">取消</n-button>
      <n-button v-if="step === 'knowledge'" @click="step = 'purpose'">下一步：用途</n-button>
      <n-button v-else-if="step === 'purpose'" @click="step = 'settings'">下一步：策略</n-button>
      <template v-else>
        <n-button v-if="!generate" :loading="busy" @click="save('draft')">保存草稿</n-button>
        <n-button type="primary" :loading="busy" @click="save('active')">
          {{ generate ? '确认生成草稿' : '保存并设为可用' }}
        </n-button>
      </template>
    </div>
  </n-modal>
</template>
