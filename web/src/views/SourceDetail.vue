<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  ChevronLeft,
  BookOpen,
  FileText,
  Plus,
  ExternalLink,
  Split,
  Merge,
  ScanText,
  Trash2,
  Download,
  Check,
  Quote,
} from 'lucide-vue-next';
import { get, post, patch, remove, download } from '../lib/api';
import { useResource, useAction, useConfirm } from '../lib/useData';
import {
  type Entity,
  type Profile,
  type Reference,
  typeLabels,
  textOf,
  dateText,
  requestId,
  locationLabel,
} from '../lib/types';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import StatusBadge from '../components/StatusBadge.vue';
import MarkdownText from '../components/MarkdownText.vue';
import EvidenceDrawer from '../components/EvidenceDrawer.vue';
import CardEditor from '../components/CardEditor.vue';
import SourceOverview from '../components/SourceOverview.vue';
const attributions: Record<string, string> = {
  author: '作者观点',
  reported: '资料转述',
  user: '用户补充',
  model: '模型归纳',
};
const route = useRoute(),
  router = useRouter();
const id = computed(() => String(route.params.id));
const { data, loading, error, reload } = useResource(() => get<any>('/sources/' + id.value), {
  source: null,
  chapters: [],
  cards: [],
  versions: [],
  agents: [],
});
const { busy, run, message } = useAction();
const confirm = useConfirm();
const selected = ref<string[]>([]),
  activeChapter = ref<string | null>(null),
  tab = ref('chapters'),
  cardType = ref<string | null>(null);
const selectedChapter = computed<Entity | undefined>(() =>
  data.value.chapters.find((c: Entity) => c.id === activeChapter.value),
);
const filteredCards = computed<Entity[]>(() =>
  data.value.cards.filter((c: Entity) => !cardType.value || c.data.type === cardType.value),
);
const selectedChars = computed(() =>
  data.value.chapters
    .filter((c: Entity) => selected.value.includes(c.id))
    .reduce(
      (sum: number, c: Entity) => sum + String(c.data.text || '').replace(/\s/g, '').length,
      0,
    ),
);
const source = computed<Entity | null>(() => data.value.source);
watch(id, () => {
  selected.value = [];
  activeChapter.value = null;
  void reload();
});
watch(
  () => data.value.chapters,
  (chapters) => {
    if (!selected.value.length)
      selected.value = chapters
        .filter((c: Entity) => c.data.selected !== false)
        .map((c: Entity) => c.id);
    if (!activeChapter.value && chapters.length) activeChapter.value = chapters[0].id;
  },
);
const editing = ref(false),
  card = ref<Entity | null>(null),
  evidence = ref<Reference | null>(null),
  evidenceOpen = ref(false);
const profiles = ref<Profile[]>([]),
  model = ref<string | null>(null),
  focus = ref(''),
  distillOpen = ref(false);
const splitOpen = ref(false),
  splitOffset = ref(1),
  chapterEditOpen = ref(false),
  chapterTitle = ref('');
const deleteOpen = ref(false),
  deleteMode = ref('file'),
  history = ref('keep'),
  impact = ref<any>(null);
const metadataOpen = ref(false),
  metadata = ref({ title: '', author: '', version: '', translator: '', note: '' });
const restoreOpen = ref(false),
  restoreCard = ref<Entity | null>(null),
  restoreVersion = ref(1);
function showEvidence(ref: Reference) {
  evidence.value = ref;
  evidenceOpen.value = true;
}
async function configure() {
  await run(async () => {
    profiles.value = await get('/profiles');
    distillOpen.value = true;
  });
}
async function distill() {
  if (!selected.value.length) {
    message.warning('请至少选择一个章节');
    return;
  }
  await run(async () => {
    const job = await post('/sources/' + id.value + '/distill', {
      chapter_ids: selected.value,
      model_profile_id: model.value || undefined,
      focus: focus.value,
      request_id: requestId(),
    });
    distillOpen.value = false;
    await router.push('/jobs?selected=' + job.id);
  }, '已提交蒸馏任务');
}
async function ocr() {
  await confirm(
    '开始 OCR 识别',
    '所选扫描页将发送到你配置的图片识别模型。相关费用由模型服务收取。',
    async () => {
      await run(async () => {
        const job = await post('/sources/' + id.value + '/ocr', {
          chapter_ids: selected.value,
          request_id: requestId(),
        });
        await router.push('/jobs?selected=' + job.id);
      });
    },
  );
}
async function merge() {
  if (selected.value.length < 2) {
    message.warning('至少选择两个章节');
    return;
  }
  await run(async () => {
    await post('/chapters/merge', { ids: selected.value });
    selected.value = [];
    activeChapter.value = null;
    await reload();
  }, '章节已合并，原始定位保留');
}
async function split() {
  if (!selectedChapter.value) return;
  await run(async () => {
    await post('/chapters/' + selectedChapter.value!.id + '/split', { offset: splitOffset.value });
    splitOpen.value = false;
    selected.value = [];
    await reload();
  }, '章节已拆分');
}
async function renameChapter() {
  if (!selectedChapter.value || !chapterTitle.value.trim()) return;
  await run(async () => {
    await patch('/chapters/' + selectedChapter.value!.id, { title: chapterTitle.value });
    chapterEditOpen.value = false;
    await reload();
  }, '章节标题已更新');
}
async function deletion() {
  await run(async () => {
    impact.value = await get(`/sources/${id.value}/impact`);
    deleteOpen.value = true;
  });
}
async function deleteSource() {
  await run(async () => {
    await remove(`/sources/${id.value}?mode=${deleteMode.value}&history=${history.value}`);
    deleteOpen.value = false;
    if (deleteMode.value === 'derived') await router.push('/library');
    else await reload();
  }, '删除请求已处理');
}
function editMetadata() {
  const s = source.value;
  if (!s) return;
  metadata.value = {
    title: s.title,
    author: s.data.author || '',
    version: s.data.edition || '',
    translator: s.data.translator || '',
    note: s.data.notes || s.data.note || '',
  };
  metadataOpen.value = true;
}
async function saveMetadata() {
  await run(async () => {
    await patch('/sources/' + id.value, {
      title: metadata.value.title,
      data: {
        author: metadata.value.author,
        edition: metadata.value.version,
        translator: metadata.value.translator,
        notes: metadata.value.note,
      },
    });
    metadataOpen.value = false;
    await reload();
  }, '资料信息已保存');
}
async function deleteCard(c: Entity) {
  await confirm(
    '删除知识卡',
    `“${c.title}”将从可用知识中移除，关联智能体和增强资产将更新状态。`,
    () =>
      run(async () => {
        await remove('/cards/' + c.id);
        await reload();
      }, '知识卡已删除'),
  );
}
async function restore() {
  if (!restoreCard.value) return;
  await run(async () => {
    await post('/cards/' + restoreCard.value!.id + '/restore', { version: restoreVersion.value });
    restoreOpen.value = false;
    await reload();
  }, '已恢复为新的知识卡版本');
}
</script>
<template>
  <RouterLink to="/library" class="back-link">
    <ChevronLeft :size="14" />
    返回书架
  </RouterLink>
  <ResourceState :loading="loading" :error="error" @retry="reload()">
    <template v-if="source">
      <PageHeader
        :title="source.title"
        :description="`${source.data.author || '作者未填写'} · ${source.data.format?.toUpperCase() || '文本资料'} · ${dateText(source.created_at)}`"
        eyebrow="SOURCE & KNOWLEDGE"
      >
        <n-button @click="editMetadata">编辑资料</n-button>
        <n-button @click="run(() => download(`/export?kind=source&id=${id}&format=markdown`))">
          <template #icon><Download :size="15" /></template>
          导出
        </n-button>
        <n-button type="primary" @click="configure">蒸馏所选章节</n-button>
      </PageHeader>
      <div class="source-summary surface">
        <StatusBadge :status="source.status" />
        <span>{{ data.chapters.length }} 个章节 / 分段</span>
        <span>{{ data.cards.length }} 张知识卡</span>
        <span>版本 {{ source.version }}</span>
        <n-tag v-if="source.data.demo || source.data.is_demo" :bordered="false" size="small">
          原创演示资料 · 非真实出版物
        </n-tag>
        <a :href="`/api/v1/sources/${id}/file`" target="_blank" class="text-link">
          查看原文件
          <ExternalLink :size="12" />
        </a>
        <n-button text type="error" @click="deletion">
          <Trash2 :size="14" />
          删除
        </n-button>
      </div>
      <n-tabs v-model:value="tab" type="line" class="source-tabs">
        <n-tab-pane name="chapters" tab="章节与原文">
          <div class="chapter-layout surface">
            <aside class="chapter-list">
              <div class="chapter-list-head">
                <n-checkbox
                  :checked="selected.length === data.chapters.length && data.chapters.length > 0"
                  :indeterminate="selected.length > 0 && selected.length < data.chapters.length"
                  @update:checked="selected = $event ? data.chapters.map((c: Entity) => c.id) : []"
                >
                  选择处理范围
                </n-checkbox>
                <span class="muted small">{{ selected.length }} / {{ data.chapters.length }}</span>
              </div>
              <div
                v-for="(c, index) in data.chapters"
                :key="c.id"
                class="chapter-row"
                :class="{ selected: activeChapter === c.id }"
              >
                <n-checkbox
                  :checked="selected.includes(c.id)"
                  @update:checked="
                    selected = $event ? [...selected, c.id] : selected.filter((v) => v !== c.id)
                  "
                  :aria-label="'选择' + c.title"
                />
                <button @click="activeChapter = c.id">
                  <span class="chapter-number">
                    {{ String(Number(index) + 1).padStart(2, '0') }}
                  </span>
                  <strong>{{ c.title }}</strong>
                  <small>
                    {{
                      String(c.data.text || '')
                        .replace(/\s/g, '')
                        .length.toLocaleString()
                    }}
                    字
                    <span v-if="!c.data.text">· 待识别 / 空内容</span>
                  </small>
                </button>
              </div>
              <div class="chapter-list-foot">
                <n-button
                  size="small"
                  @click="merge"
                  :disabled="selected.length < 2"
                  :loading="busy"
                >
                  <template #icon><Merge :size="13" /></template>
                  合并选中
                </n-button>
                <n-button size="small" @click="ocr" :loading="busy">
                  <template #icon><ScanText :size="13" /></template>
                  OCR
                </n-button>
              </div>
            </aside>
            <article class="chapter-reader" v-if="selectedChapter">
              <div class="section-heading">
                <div>
                  <p class="eyebrow">
                    {{ locationLabel(selectedChapter.data.locator) }}
                  </p>
                  <h2>{{ selectedChapter.title }}</h2>
                </div>
                <div class="inline-actions">
                  <n-button
                    size="small"
                    @click="
                      chapterTitle = selectedChapter.title;
                      chapterEditOpen = true;
                    "
                  >
                    改标题
                  </n-button>
                  <n-button
                    size="small"
                    @click="
                      splitOffset = Math.max(
                        1,
                        Math.floor((selectedChapter.data.text || '').length / 2),
                      );
                      splitOpen = true;
                    "
                    :disabled="!selectedChapter.data.text"
                  >
                    <template #icon><Split :size="13" /></template>
                    拆分
                  </n-button>
                </div>
              </div>
              <n-alert v-if="selectedChapter.data.ocr" type="info" :show-icon="false">
                此段来自 OCR。识别可能有误，请对照原文件核对。
              </n-alert>
              <p v-if="selectedChapter.data.text" class="source-text">
                {{ selectedChapter.data.text }}
              </p>
              <div v-else class="small-empty">
                <ScanText :size="30" />
                <h3>这一页尚未提取到文字</h3>
                <p class="muted">可使用具备图片识别能力的模型进行 OCR，或检查原文件是否可读。</p>
                <n-button @click="ocr" style="margin-top: 16px">识别所选页面</n-button>
              </div>
            </article>
            <div v-else class="chapter-reader muted">选择左侧章节查看真实解析内容。</div>
          </div>
        </n-tab-pane>
        <n-tab-pane name="cards" :tab="`知识卡 (${data.cards.length})`">
          <div class="toolbar">
            <n-select
              v-model:value="cardType"
              :options="
                ['concept', 'claim', 'method', 'boundary'].map((v) => ({
                  label: typeLabels[v],
                  value: v,
                }))
              "
              clearable
              placeholder="全部类型"
              style="width: 160px"
            />
            <span class="muted small">AI 生成不代表内容已被核实。可修改、标记疑问或核对来源。</span>
            <n-button
              style="margin-left: auto"
              @click="
                card = null;
                editing = true;
              "
            >
              <template #icon><Plus :size="14" /></template>
              个人补充
            </n-button>
          </div>
          <ResourceState
            :empty="!filteredCards.length"
            title="还没有知识卡"
            description="选择章节并完成蒸馏，或者添加自己的知识补充。"
          >
            <div class="knowledge-grid">
              <article v-for="c in filteredCards" :key="c.id" class="knowledge-card surface">
                <div class="knowledge-card-top">
                  <n-tag size="small" :bordered="false">
                    {{ typeLabels[c.data.type] || c.data.type }}
                  </n-tag>
                  <StatusBadge :status="c.data.review_status || 'pending'" />
                  <span class="muted small">v{{ c.version }}</span>
                </div>
                <h3>{{ c.title }}</h3>
                <MarkdownText :text="textOf(c.data.content)" />
                <p class="attribution">
                  {{ attributions[c.data.attribution] || c.data.attribution || '来源归属待核对' }}
                  <span v-if="(c.data.edit_origin || c.data.edit_source)?.includes('user')">
                    · 用户已编辑
                  </span>
                </p>
                <div class="card-evidence">
                  <n-button
                    v-for="(r, i) in c.data.references || []"
                    :key="i"
                    text
                    size="small"
                    @click="showEvidence(r)"
                  >
                    <template #icon><Quote :size="12" /></template>
                    {{ r.label || `来源 ${Number(i) + 1}` }}
                  </n-button>
                  <span v-if="!c.data.references?.length" class="muted small">暂无原文依据</span>
                </div>
                <div class="knowledge-card-actions">
                  <n-button
                    text
                    size="small"
                    @click="
                      card = c;
                      editing = true;
                    "
                  >
                    编辑与核对
                  </n-button>
                  <n-button
                    text
                    size="small"
                    v-if="c.version > 1"
                    @click="
                      restoreCard = c;
                      restoreVersion = c.version - 1;
                      restoreOpen = true;
                    "
                  >
                    恢复版本
                  </n-button>
                  <n-button text size="small" type="error" @click="deleteCard(c)">删除</n-button>
                </div>
              </article>
            </div>
          </ResourceState>
        </n-tab-pane>
        <n-tab-pane name="overview" tab="总览与覆盖">
          <SourceOverview :source="source" :chapters="data.chapters" :versions="data.versions" />
        </n-tab-pane>
        <n-tab-pane name="agents" tab="关联智能体">
          <div class="surface item-list">
            <div v-for="a in data.agents" :key="a.id" class="list-item">
              <div class="avatar">{{ a.title.slice(0, 1) }}</div>
              <div class="list-item-main">
                <h3>{{ a.title }}</h3>
                <p class="muted small">{{ a.data.purpose }}</p>
              </div>
              <StatusBadge :status="a.status" />
              <n-button size="small" @click="router.push('/agents?selected=' + a.id)">
                查看
              </n-button>
            </div>
            <div v-if="!data.agents.length" class="panel-pad muted">
              尚未基于这份资料创建智能体。
            </div>
          </div>
          <n-button style="margin-top: 16px" @click="router.push('/agents?source=' + id)">
            从这份资料创建智能体
          </n-button>
        </n-tab-pane>
      </n-tabs>
    </template>
  </ResourceState>
  <n-modal v-model:show="distillOpen" preset="card" title="确认本次蒸馏" style="width: 620px">
    <p>
      已选择
      <strong>{{ selected.length }}</strong>
      个章节，共
      <strong>{{ selectedChars.toLocaleString() }}</strong>
      个非空白字符。
    </p>
    <n-alert v-if="selectedChars > 500000" type="error" style="margin-top: 16px">
      超过默认 50 万字符限制，请缩小章节范围。
    </n-alert>
    <n-form style="margin-top: 20px">
      <n-form-item label="模型">
        <n-select
          v-model:value="model"
          :options="
            profiles
              .filter((p) => p.enabled && !p.capabilities?.embedding)
              .map((p) => ({ label: `${p.name} · ${p.model}`, value: p.id }))
          "
          clearable
          placeholder="使用默认蒸馏模型"
        />
      </n-form-item>
      <n-form-item label="关注的问题（可选）">
        <n-input
          v-model:value="focus"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 6 }"
          placeholder="你希望从这份资料中重点理解什么？"
        />
      </n-form-item>
    </n-form>
    <n-alert type="info" :show-icon="false">
      所选原文将发送到指定模型服务，生成知识卡、章节摘要、关系与覆盖报告。模型费用由服务商收取；关掉网页后，已确认任务会继续。
    </n-alert>
    <div class="modal-footer">
      <n-button @click="distillOpen = false">返回调整</n-button>
      <n-button
        type="primary"
        :loading="busy"
        :disabled="!selected.length || selectedChars > 500000"
        @click="distill"
      >
        确认开始
      </n-button>
    </div>
  </n-modal>
  <n-modal v-model:show="splitOpen" preset="card" title="拆分章节" style="width: 520px">
    <p class="field-hint">
      在指定字符位置拆成两段，保留对应原文位置。当前共
      {{ selectedChapter?.data.text?.length || 0 }} 字符。
    </p>
    <n-input-number
      v-model:value="splitOffset"
      :min="1"
      :max="(selectedChapter?.data.text?.length || 2) - 1"
    />
    <p class="split-preview">
      {{ selectedChapter?.data.text?.slice(Math.max(0, splitOffset - 60), splitOffset) }}
      <strong>｜拆分位置｜</strong>
      {{ selectedChapter?.data.text?.slice(splitOffset, splitOffset + 60) }}
    </p>
    <div class="modal-footer">
      <n-button @click="splitOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="split">确认拆分</n-button>
    </div>
  </n-modal>
  <n-modal v-model:show="chapterEditOpen" preset="card" title="修改章节标题" style="width: 460px">
    <n-input v-model:value="chapterTitle" />
    <div class="modal-footer">
      <n-button @click="chapterEditOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="renameChapter">保存</n-button>
    </div>
  </n-modal>
  <n-modal v-model:show="metadataOpen" preset="card" title="资料信息" style="width: 600px">
    <n-form>
      <n-form-item label="标题">
        <n-input v-model:value="metadata.title" :maxlength="100" />
      </n-form-item>
      <div class="form-grid">
        <n-form-item label="作者"><n-input v-model:value="metadata.author" /></n-form-item>
        <n-form-item label="版本 / 出版信息">
          <n-input v-model:value="metadata.version" />
        </n-form-item>
        <n-form-item label="译者"><n-input v-model:value="metadata.translator" /></n-form-item>
      </div>
      <n-form-item label="个人备注（不混入原文）">
        <n-input v-model:value="metadata.note" type="textarea" />
      </n-form-item>
    </n-form>
    <div class="modal-footer">
      <n-button @click="metadataOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="saveMetadata">保存</n-button>
    </div>
  </n-modal>
  <n-modal v-model:show="deleteOpen" preset="card" title="确认删除范围" style="width: 650px">
    <n-alert type="warning" :show-icon="false">
      删除不会自动清除你所有独立笔记。请明确选择原文件、知识以及历史摘录的处理范围。
    </n-alert>
    <n-radio-group v-model:value="deleteMode" class="delete-options">
      <n-radio value="file">仅删除原始文件，保留知识卡与历史记录</n-radio>
      <n-radio value="derived">删除资料及派生知识，包括所有引用本资料的混合知识卡</n-radio>
    </n-radio-group>
    <p class="field-hint">受影响图谱、Skill、相关知识性记忆将保留并置灰，停止使用。</p>
    <div v-if="impact" class="subtle-note">
      关联影响：{{
        Object.entries(impact)
          .filter(([, v]) => typeof v === 'number')
          .map(([k, v]) => `${typeLabels[k] || k} ${v}`)
          .join(' · ') || textOf(impact)
      }}
    </div>
    <n-form-item label="历史消息、成果和实践记录里的相关摘录" style="margin-top: 20px">
      <n-select
        v-model:value="history"
        :options="[
          { label: '保留历史摘录，并标记来源失效', value: 'keep' },
          { label: '清除相关摘录，保留独立原创内容', value: 'redact' },
        ]"
      />
    </n-form-item>
    <div class="modal-footer">
      <n-button @click="deleteOpen = false">取消</n-button>
      <n-button type="error" :loading="busy" @click="deleteSource">确认删除</n-button>
    </div>
  </n-modal>
  <n-modal v-model:show="restoreOpen" preset="card" title="恢复知识卡版本" style="width: 460px">
    <p class="field-hint">恢复会创建一个新版本，已存在的会话不受影响。</p>
    <n-input-number v-model:value="restoreVersion" :min="1" :max="restoreCard?.version || 1" />
    <div class="modal-footer">
      <n-button @click="restoreOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="restore">恢复</n-button>
    </div>
  </n-modal>
  <CardEditor v-model:show="editing" :card="card" :source-id="id" @saved="reload(true)" />
  <EvidenceDrawer v-model:show="evidenceOpen" :reference="evidence" />
</template>
<style scoped>
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 18px;
}
.source-summary {
  display: flex;
  gap: 20px;
  align-items: center;
  padding: 15px 20px;
  font-size: 12px;
  color: var(--muted);
  flex-wrap: wrap;
}
.source-summary a {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
}
.source-tabs {
  margin-top: 24px;
}
.chapter-layout {
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr);
  min-height: 520px;
  overflow: hidden;
}
.chapter-list {
  border-right: 1px solid var(--border);
  background: var(--surface-subtle);
}
.chapter-list-head {
  padding: 17px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
}
.chapter-row {
  display: flex;
  align-items: center;
  padding: 0 14px;
  gap: 10px;
  border-bottom: 1px solid var(--border);
}
.chapter-row.selected {
  background: var(--accent-soft);
}
.chapter-row button {
  padding: 15px 0;
  text-align: left;
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  cursor: pointer;
}
.chapter-row strong {
  display: block;
  font-weight: 500;
  font-size: 12px;
}
.chapter-row small {
  display: block;
  color: var(--muted);
  font-size: 10px;
  margin-top: 4px;
}
.chapter-number {
  font-size: 9px;
  color: var(--muted);
}
.chapter-list-foot {
  padding: 16px;
  display: flex;
  gap: 8px;
}
.chapter-reader {
  padding: 28px;
  max-height: 750px;
  overflow-y: auto;
}
.source-text {
  white-space: pre-wrap;
  font-family: 'Songti SC', 'Noto Serif SC', Georgia, serif;
  font-size: 16px;
  line-height: 2.15;
  letter-spacing: 0.2px;
  margin-top: 22px;
  color: var(--text-secondary);
}
.knowledge-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.knowledge-card {
  padding: 24px;
}
.knowledge-card-top {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 16px;
}
.knowledge-card-top > span:last-child {
  margin-left: auto;
}
.knowledge-card h3 {
  font-size: 17px;
  margin-bottom: 14px;
}
.knowledge-card .markdown-content {
  font-size: 13px;
}
.attribution {
  font-size: 10px;
  color: var(--muted);
  margin-top: 16px;
}
.card-evidence {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.knowledge-card-actions {
  display: flex;
  gap: 16px;
  margin-top: 16px;
}
.knowledge-card-actions > *:last-child {
  margin-left: auto;
}
.small-empty {
  text-align: center;
  padding: 60px 20px;
}
.small-empty h3 {
  margin: 16px 0;
}
.delete-options {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin: 24px 0;
}
.split-preview {
  background: var(--surface-subtle);
  padding: 16px;
  margin-top: 20px;
  font-size: 12px;
  white-space: pre-wrap;
}
.split-preview strong {
  color: var(--accent);
}
@media (max-width: 1200px) {
  .chapter-layout {
    grid-template-columns: 230px minmax(0, 1fr);
  }
  .knowledge-grid {
    grid-template-columns: 1fr;
  }
  .chapter-reader {
    padding: 22px;
  }
}
</style>
