<script setup lang="ts">
import { switchArea } from '../lib/navigation';
import { ref, computed, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { defineAsyncComponent } from 'vue';
const SkillMaintenance = defineAsyncComponent(
  () => import('../components/maintenance/SkillMaintenance.vue'),
);
const props = defineProps<{ management?: boolean }>();
const maintenance = ref<InstanceType<typeof SkillMaintenance> | null>(null);
import { ListChecks, Play, Download, CheckCircle2, ChevronRight, History } from 'lucide-vue-next';
import { get, post, download } from '../lib/api';
import { useResource, useAction } from '../lib/useData';
import { type Entity, textOf, dateText, requestId } from '../lib/types';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import StatusBadge from '../components/StatusBadge.vue';
import MarkdownText from '../components/MarkdownText.vue';
import PracticeJobs from '../components/PracticeJobs.vue';
const pendingPracticeJob = ref(false);
const router = useRouter(),
  route = useRoute();
const {
  data: skills,
  loading,
  error,
  reload,
} = useResource(() => get<Entity[]>('/skills'), [], 8000);
const { data: runs, reload: reloadRuns } = useResource(
  () => (props.management ? Promise.resolve<Entity[]>([]) : get<Entity[]>('/runs')),
  [],
  4000,
);
const { busy, run, message } = useAction();
const agents = ref<Entity[]>([]);
const tab = ref(props.management ? 'methods' : String(route.query.tab || 'methods')),
  selected = ref<Entity | null>(null),
  detailOpen = ref(false);
const agentId = ref<string | null>(null);
const startOpen = ref(false),
  startSkill = ref<Entity | null>(null),
  startInputs = ref<Record<string, string>>({});
const practiceOpen = ref(false),
  practice = ref<Entity | null>(null),
  answer = ref(''),
  reflection = ref(''),
  useAI = ref(false);
const practiceSteps = computed(() => practice.value?.data.skill_snapshot?.data.steps || []);
const currentStep = computed(() => practiceSteps.value[practice.value?.data.step_index || 0]);
onMounted(
  () =>
    void run(async () => {
      agents.value = await get('/agents');
    }),
);
watch(runs, (items) => {
  if (practice.value) {
    const updated = items.find((r) => r.id === practice.value!.id);
    if (updated) practice.value = updated;
  }
});
function start(skill: Entity) {
  if (props.management) {
    void router.push({ path: '/skills', query: { selected: skill.id, start: '1' } });
    return;
  }
  startSkill.value = skill;
  startInputs.value = Object.fromEntries(
    (skill.data.inputs || []).map((name: string) => [name, '']),
  );
  agentId.value = skill.data.agent_id || null;
  startOpen.value = true;
}
async function startRun() {
  if (!startSkill.value) return;
  await run(async () => {
    practice.value = await post(`/skills/${startSkill.value!.id}/runs`, {
      inputs: startInputs.value,
      agent_id: agentId.value,
    });
    practiceOpen.value = true;
    void router.replace({ query: { tab: 'runs', run: practice.value!.id } });
    startOpen.value = false;
    answer.value = '';
    reflection.value = '';
    await reloadRuns();
  }, '本次实践已开始');
}
function openRun(r: Entity) {
  if (route.query.run !== r.id)
    void router.replace({ query: { ...route.query, tab: 'runs', run: r.id } });
  practice.value = r;
  reflection.value = r.data.reflection || '';
  answer.value = '';
  practiceOpen.value = true;
}
async function advance() {
  if (!practice.value || !answer.value.trim()) {
    message.warning('请记录实际完成的结果');
    return;
  }
  await run(async () => {
    const result = await post(`/runs/${practice.value!.id}/advance`, {
      answer: answer.value,
      use_ai: useAI.value,
      request_id: requestId(),
    });
    answer.value = '';
    if (result.kind === 'job') message.info('AI 引导任务已提交，完成后会保存当前步骤结果。');
    else practice.value = result;
    await reloadRuns();
  }, '实践结果已提交');
}
async function review() {
  if (!practice.value) return;
  await run(async () => {
    practice.value = await post(`/runs/${practice.value!.id}/review`, {
      reflection: reflection.value,
    });
    await reloadRuns();
  }, '复盘已保存');
}
watch(
  [skills, () => route.query.selected],
  () => {
    const skill = skills.value.find((s) => s.id === route.query.selected);
    if (skill) {
      const changed = selected.value?.id !== skill.id;
      selected.value = skill;
      if (changed) {
        if (route.query.start && !props.management) start(skill);
        else detailOpen.value = true;
      }
    } else if (!route.query.selected) {
      detailOpen.value = false;
      selected.value = null;
    }
  },
  { immediate: true },
);
watch(
  [runs, () => route.query.run],
  () => {
    const item = runs.value.find((r) => r.id === route.query.run);
    if (item && !practiceOpen.value) openRun(item);
  },
  { immediate: true },
);
watch(
  () => route.query.tab,
  (value) => {
    tab.value = props.management ? 'methods' : String(value || 'methods');
  },
);
watch(tab, (value) => {
  void router.replace({ query: { ...route.query, tab: value } });
});
</script>
<template>
  <PageHeader
    eyebrow="KNOWLEDGE INTO PRACTICE"
    :title="management ? 'Skill 管理' : '实践 Skills'"
    description="把方法变成可重复的小步骤，保留每次实践的真实结果。"
  >
    <n-button
      v-if="management"
      @click="router.push(switchArea(route, management ? 'front' : 'admin'))"
    >
      前台查看
    </n-button>
    <SkillMaintenance v-if="management" ref="maintenance" @changed="reload(true)" />
    <n-button v-else @click="router.push(switchArea(route, management ? 'front' : 'admin'))">
      管理方法
    </n-button>
  </PageHeader>
  <n-tabs v-model:value="tab" type="line">
    <n-tab-pane name="methods" :tab="`方法库 (${skills.length})`">
      <ResourceState
        :loading="loading"
        :error="error"
        :empty="!skills.length"
        title="让方法真正用起来"
        description="从已蒸馏的方法卡生成 Skill，由智能体引导你逐步实践；每次执行独立保存进度。"
        @retry="reload()"
      >
        <template #icon><ListChecks :size="36" :stroke-width="1.3" /></template>
        <template #action>
          <n-button @click="router.push('/admin/skills')">去后台维护方法</n-button>
        </template>
        <div class="skill-grid">
          <article
            v-for="s in skills"
            :key="s.id"
            class="skill-card surface"
            :class="{ 'disabled-asset': s.status === 'disabled' }"
          >
            <div class="section-heading">
              <span class="skill-symbol"><ListChecks :size="21" /></span>
              <StatusBadge :status="s.status" />
            </div>
            <h2>{{ s.title }}</h2>
            <p>{{ textOf(s.data.description) }}</p>
            <div class="skill-meta">
              <span>{{ s.data.steps?.length || 0 }} 个步骤</span>
              <span>{{ s.data.card_ids?.length || 0 }} 张方法卡</span>
              <span>v{{ s.version }}</span>
            </div>
            <div class="skill-preview">
              <div v-for="(step, i) in (s.data.steps || []).slice(0, 3)" :key="i">
                <span>{{ Number(i) + 1 }}</span>
                {{ step.title || `步骤 ${Number(i) + 1}` }}
              </div>
            </div>
            <p class="error-text" v-if="s.status === 'disabled'">
              {{ s.data.disabled_reason || '来源已失效，修复前无法执行。' }}
            </p>
            <div class="skill-actions">
              <n-button
                type="primary"
                size="small"
                :disabled="s.status === 'disabled'"
                @click="start(s)"
              >
                <Play :size="13" />
                开始一次实践
              </n-button>
              <n-button
                text
                size="small"
                @click="router.push({ query: { ...route.query, selected: s.id } })"
              >
                查看方法
              </n-button>
            </div>
          </article>
        </div>
      </ResourceState>
    </n-tab-pane>
    <n-tab-pane v-if="!management" name="runs" :tab="`实践记录 (${runs.length})`">
      <ResourceState
        :empty="!runs.length"
        title="每一次实践，都有自己的记录"
        description="从方法库开始一次实践，你的输入、步骤结果与复盘会保存在这里。"
      >
        <div class="surface item-list">
          <button v-for="r in runs" :key="r.id" class="practice-row" @click="openRun(r)">
            <div class="avatar"><History :size="18" /></div>
            <div class="list-item-main">
              <h3>{{ r.title }}</h3>
              <p class="list-item-meta">
                {{ r.data.step_index || 0 }} /
                {{ r.data.skill_snapshot?.data.steps?.length || 0 }} 步 ·
                {{ dateText(r.updated_at) }}
              </p>
            </div>
            <StatusBadge :status="r.status" />
            <ChevronRight :size="16" />
          </button>
        </div>
      </ResourceState>
    </n-tab-pane>
  </n-tabs>
  <n-drawer
    v-model:show="detailOpen"
    @update:show="
      (value: boolean) => {
        if (!value) {
          selected = null;
          void router.replace({ query: { ...route.query, selected: undefined, start: undefined } });
        }
      }
    "
    :width="600"
  >
    <n-drawer-content :title="selected?.title" closable>
      <template v-if="selected">
        <n-alert v-if="selected.status === 'disabled'" type="warning">
          方法来源已失效。记录仍保留，修复依赖后才能执行。
        </n-alert>
        <MarkdownText :text="textOf(selected.data.description)" />
        <h3 style="margin-top: 22px">适用边界</h3>
        <MarkdownText :text="textOf(selected.data.limitations) || '尚未填写'" />
        <div v-for="(s, i) in selected.data.steps || []" :key="i" class="method-step">
          <span>{{ Number(i) + 1 }}</span>
          <div>
            <h3>{{ s.title }}</h3>
            <MarkdownText :text="s.instruction" />
            <p class="subtle-note">产物：{{ s.output || '未填写' }}</p>
          </div>
        </div>
        <div class="inline-actions section-spaced">
          <n-button
            type="primary"
            :disabled="selected.status === 'disabled'"
            @click="start(selected)"
          >
            开始实践
          </n-button>
          <n-button v-if="management" @click="maintenance?.edit(selected)">
            {{ selected.status === 'disabled' ? '修复依赖' : '编辑方法' }}
          </n-button>
          <n-button
            v-if="!management"
            @click="router.push({ path: '/admin/skills', query: { selected: selected.id } })"
          >
            维护此方法
          </n-button>
          <n-button
            @click="
              run(() =>
                download(`/export?kind=skill&id=${selected!.id}&format=markdown`, 'SKILL.md'),
              )
            "
          >
            <Download :size="14" />
            导出 SKILL.md
          </n-button>
          <n-button v-if="management" type="error" @click="maintenance?.del(selected)">
            删除
          </n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
  <n-modal
    v-if="!management"
    v-model:show="startOpen"
    preset="card"
    :title="'开始实践 · ' + (startSkill?.title || '')"
    style="width: 600px"
  >
    <n-form>
      <n-form-item
        v-for="name in startSkill?.data.inputs || []"
        :key="textOf(name)"
        :label="textOf(name)"
      >
        <n-input
          v-model:value="startInputs[textOf(name)]"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
        />
      </n-form-item>
      <n-form-item label="引导智能体（可选）">
        <n-select
          v-model:value="agentId"
          clearable
          :options="
            agents
              .filter((a) => !['disabled', 'draft', 'archived'].includes(a.status))
              .map((a) => ({ label: a.title, value: a.id }))
          "
        />
      </n-form-item>
    </n-form>
    <p class="field-hint">新建独立实践记录，固定当前 Skill 版本。仅创建记录不调用模型。</p>
    <div class="modal-footer">
      <n-button @click="startOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="startRun">开始记录</n-button>
    </div>
  </n-modal>
  <n-drawer
    v-if="!management"
    v-model:show="practiceOpen"
    @update:show="
      (value: boolean) => {
        if (!value) void router.replace({ query: { ...route.query, run: undefined } });
      }
    "
    :width="720"
  >
    <n-drawer-content :title="practice?.title || '实践记录'" closable>
      <template v-if="practice">
        <div class="inline-actions">
          <StatusBadge :status="practice.status" />
          <span class="muted small">
            方法版本 {{ practice.data.skill_version }} · 已完成
            {{ practice.data.step_index || 0 }} / {{ practiceSteps.length }} 步
          </span>
        </div>
        <p v-if="practice.data.agent_snapshot" class="muted small">
          引导智能体：{{ practice.data.agent_snapshot.title }} · v{{ practice.data.agent_version }}
        </p>
        <p v-if="practice.data.skill_snapshot.data.completion_criteria" class="muted">
          完成标准：{{ practice.data.skill_snapshot.data.completion_criteria }}
        </p>
        <n-progress
          type="line"
          :percentage="
            Math.round((100 * (practice.data.step_index || 0)) / Math.max(1, practiceSteps.length))
          "
          :show-indicator="false"
          style="margin: 18px 0"
        />
        <n-collapse>
          <n-collapse-item title="本次输入" name="inputs">
            <div v-for="(value, key) in practice.data.inputs" :key="key">
              <strong class="small">{{ key }}</strong>
              <p class="muted small">{{ textOf(value) }}</p>
            </div>
          </n-collapse-item>
        </n-collapse>
        <div v-for="(result, i) in practice.data.results || []" :key="i" class="completed-step">
          <h3>
            <CheckCircle2 :size="16" />
            {{ result.step?.title || `步骤 ${Number(i) + 1}` }}
          </h3>
          <p class="practice-answer">{{ result.answer }}</p>
          <div v-if="result.guidance" class="subtle-note">
            <h4>AI 引导与反馈</h4>
            <MarkdownText :text="result.guidance" />
          </div>
        </div>
        <PracticeJobs
          :run-id="practice.id"
          @pending="pendingPracticeJob = $event"
          @changed="reloadRuns()"
        />
        <section v-if="currentStep && practice.status !== 'disabled'" class="current-step">
          <p class="eyebrow">STEP {{ practice.data.step_index + 1 }}</p>
          <h2>{{ currentStep.title }}</h2>
          <MarkdownText :text="currentStep.instruction" />
          <p class="subtle-note">本步产物：{{ currentStep.output || '记录实际结果' }}</p>
          <n-form-item label="记录实际完成了什么、观察到什么" style="margin-top: 20px">
            <n-input
              v-model:value="answer"
              type="textarea"
              :autosize="{ minRows: 5, maxRows: 12 }"
              placeholder="也可以记录：这个方法暂时不适用，原因是…"
            />
          </n-form-item>
          <n-checkbox v-model:checked="useAI">请 AI 基于本步结果给出引导（会调用模型）</n-checkbox>
          <n-button
            type="primary"
            :loading="busy"
            :disabled="pendingPracticeJob"
            @click="advance"
            style="margin-top: 16px"
          >
            保存本步并继续
          </n-button>
        </section>
        <n-alert v-if="practice.status === 'disabled'" type="warning" style="margin-top: 20px">
          来源或方法已失效，不能继续执行；既有记录保留。
        </n-alert>
        <section class="section-spaced">
          <h3>实践复盘</h3>
          <p class="field-hint">哪些方法有用，哪些前提不成立？无需把所有结果都归因于自己。</p>
          <n-input
            v-model:value="reflection"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 10 }"
          />
          <n-button :loading="busy" @click="review" style="margin-top: 14px">保存复盘</n-button>
        </section>
      </template>
    </n-drawer-content>
  </n-drawer>
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
