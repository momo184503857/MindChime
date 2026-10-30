<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { get, post, patch } from '../../lib/api';
import { useAction } from '../../lib/useData';
import { type Entity } from '../../lib/types';
import PageHeader from '../../components/PageHeader.vue';
import StatusBadge from '../../components/StatusBadge.vue';
import ThoughtTaskDialog from '../../components/thought/ThoughtTaskDialog.vue';
import CognitiveProfileDrawer from '../../components/thought/CognitiveProfileDrawer.vue';
import ThoughtResultDrawer from '../../components/thought/ThoughtResultDrawer.vue';
const route = useRoute();
const router = useRouter(),
  { busy, run } = useAction();
const persons = ref<Entity[]>([]),
  sources = ref<Entity[]>([]),
  profiles = ref<Entity[]>([]),
  results = ref<Entity[]>([]),
  models = ref<any[]>([]),
  loading = ref(true),
  error = ref('');
const personOpen = ref(false),
  personTitle = ref(''),
  personDescription = ref(''),
  editingPerson = ref<Entity | null>(null),
  personId = ref<string | null>(null),
  taskOpen = ref(false);
const detail = ref<Entity | null>(null),
  detailOpen = ref(false),
  resultOpen = ref(false),
  selectedResult = ref<Entity | null>(null);
const profileList = computed(() =>
  profiles.value.filter((p) => !personId.value || p.data.person_id === personId.value),
);
let timer: ReturnType<typeof setInterval>;
async function load() {
  try {
    [persons.value, sources.value, profiles.value, results.value, models.value] = await Promise.all(
      [
        get('/persons'),
        get('/sources'),
        get('/cognitive-profiles'),
        get('/distillations?distillation_type=thought'),
        get('/profiles'),
      ],
    );
    error.value = '';
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
onMounted(() => {
  void load().then(() => {
    if (route.query.create) taskOpen.value = true;
  });
  timer = setInterval(() => void load(), 12000);
});
onUnmounted(() => clearInterval(timer));
function editPerson(p: Entity | null = null) {
  editingPerson.value = p;
  personTitle.value = p?.title || '';
  personDescription.value = p?.data.description || '';
  personOpen.value = true;
}
async function savePerson() {
  await run(async () => {
    const body = { title: personTitle.value, data: { description: personDescription.value } };
    if (editingPerson.value) await patch('/persons/' + editingPerson.value.id, body);
    else await post('/persons', body);
    personOpen.value = false;
    await load();
  }, '人物已保存');
}
function newTask() {
  taskOpen.value = true;
}
function inspect(p: Entity) {
  detail.value = p;
  detailOpen.value = true;
}
function viewResult(r: Entity) {
  selectedResult.value = r;
  resultOpen.value = true;
}
async function submitted(job: Entity) {
  await load();
  await router.push({ path: '/admin/jobs', query: { selected: job.id } });
}
</script>
<template>
  <PageHeader
    title="人物与思想蒸馏"
    description="女娲从人物多份资料提炼思考方式，与知识蒸馏独立运行、审核和发布。"
  >
    <n-button @click="editPerson()">新建人物</n-button>
    <n-button type="primary" @click="newTask">女娲思想蒸馏</n-button>
  </PageHeader>
  <n-alert v-if="error" type="error">{{ error }}</n-alert>
  <div class="toolbar">
    <n-form-item label="人物筛选" label-placement="left" style="margin-bottom: 0; min-width: 280px">
      <n-select
        v-model:value="personId"
        clearable
        filterable
        placeholder="全部人物"
        :options="persons.map((p) => ({ label: p.title, value: p.id }))"
      />
    </n-form-item>
    <n-button @click="load">刷新</n-button>
    <n-button @click="router.push('/admin/publications')">发布管理</n-button>
  </div>
  <section class="section-spaced">
    <h2>人物资料</h2>
    <div class="grid-two">
      <article v-for="p in persons" :key="p.id" class="surface panel-pad">
        <div class="section-heading">
          <h3>{{ p.title }}</h3>
          <n-button size="small" @click="editPerson(p)">编辑人物</n-button>
        </div>
        <p class="muted">{{ p.data.description || '尚未填写简介' }}</p>
      </article>
    </div>
    <p v-if="!persons.length && !loading" class="muted">
      先新建人物，再选择已导入的多份资料；也可在任务中主动开启联网采集。
    </p>
  </section>
  <section class="section-spaced">
    <h2>独立思想资产</h2>
    <div class="grid-two">
      <article v-for="p in profileList" :key="p.id" class="surface panel-pad">
        <h3>{{ p.title }}</h3>
        <div class="inline-actions">
          <StatusBadge :status="p.status" />
          <span>v{{ p.version }}</span>
          <span>
            {{ p.data.rules?.filter((r: any) => r.review_status === 'verified').length || 0 }}
            条人工确认
          </span>
        </div>
        <p class="muted">
          {{ p.data.source_ids?.length || 0 }} 份资料 · {{ p.data.rules?.length || 0 }} 条候选规则
        </p>
        <n-button @click="inspect(p)">核对与审核思想规则</n-button>
      </article>
    </div>
    <p v-if="!profileList.length && !loading" class="muted">
      尚无思想画像。知识卡片不会自动转换为人物思想。
    </p>
  </section>
  <section class="section-spaced">
    <h2>思想蒸馏批次</h2>
    <div class="surface item-list">
      <article v-for="r in results" :key="r.id" class="list-item">
        <div class="list-item-main">
          <strong>{{ r.title }}</strong>
          <p class="muted small">
            {{ r.data.allow_network ? '允许联网' : '仅本地资料' }} ·
            {{ r.data.source_ids?.length || 0 }} 份资料
          </p>
        </div>
        <StatusBadge :status="r.status" />
        <n-button size="small" @click="viewResult(r)">过程与测试</n-button>
        <n-button
          size="small"
          @click="router.push({ path: '/admin/jobs', query: { selected: r.data.job_id } })"
        >
          任务详情
        </n-button>
      </article>
    </div>
  </section>
  <n-modal
    v-model:show="personOpen"
    preset="card"
    :title="editingPerson ? '编辑人物' : '新建人物'"
    style="width: 560px"
  >
    <n-form>
      <n-form-item label="人物名称">
        <n-input v-model:value="personTitle" :maxlength="100" />
      </n-form-item>
      <n-form-item label="简介与身份辨识">
        <n-input v-model:value="personDescription" type="textarea" :maxlength="5000" />
      </n-form-item>
    </n-form>
    <div class="modal-footer">
      <n-button @click="personOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" :disabled="!personTitle.trim()" @click="savePerson">
        保存人物
      </n-button>
    </div>
  </n-modal>

  <ThoughtTaskDialog
    v-model:show="taskOpen"
    :persons="persons"
    :sources="sources"
    :models="models"
    :default-person-id="personId"
    :default-source-id="typeof route.query.source === 'string' ? route.query.source : undefined"
    @submitted="submitted"
  />
  <CognitiveProfileDrawer v-model:show="detailOpen" :profile="detail" @changed="load" />
  <ThoughtResultDrawer v-model:show="resultOpen" :result="selectedResult" @changed="load" />
</template>
