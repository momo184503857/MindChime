<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { Plus, Search, BookOpen, UploadCloud, FileText, Sparkles } from 'lucide-vue-next';
import { get, post, upload } from '../lib/api';
import { useResource, useAction } from '../lib/useData';
import { type Entity, errorText } from '../lib/types';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import LibraryShelf from '../components/LibraryShelf.vue';
const router = useRouter(),
  route = useRoute();
const { data: sources, loading, error, reload } = useResource(() => get<Entity[]>('/sources'), []);
const { busy, run, message } = useAction();
const q = ref(''),
  filter = ref<string | null>(null);
const filtered = computed(() =>
  sources.value.filter(
    (s) =>
      (!q.value ||
        `${s.title} ${s.data.author || ''}`.toLowerCase().includes(q.value.toLowerCase())) &&
      (!filter.value || s.status === filter.value),
  ),
);
const open = ref(false),
  tab = ref('file');
const fileInput = ref<HTMLInputElement | null>(null);
const files = ref<File[]>([]);
const title = ref(''),
  author = ref(''),
  text = ref(''),
  duplicate = ref('reject'),
  versionSource = ref<string | null>(null);
const results = ref<{ name: string; ok: boolean; message: string; id?: string }[]>([]);
const dragging = ref(false);
const statuses = computed(() =>
  [...new Set(sources.value.map((s) => s.status))].map((s) => ({
    label:
      (
        { parsed: '已解析', needs_ocr: '待 OCR', active: '可用', failed: '失败' } as Record<
          string,
          string
        >
      )[s] || s,
    value: s,
  })),
);
function pick(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files || []);
  results.value = [];
}
function drop(event: DragEvent) {
  dragging.value = false;
  files.value = Array.from(event.dataTransfer?.files || []);
  results.value = [];
}
async function importData() {
  if (duplicate.value === 'version' && !versionSource.value) {
    message.warning('请选择要添加版本的资料');
    return;
  }
  if (tab.value === 'text') {
    if (!title.value.trim() || !text.value.trim()) {
      message.warning('请填写标题和正文');
      return;
    }
    await run(async () => {
      const result = await post<{ source: Entity }>('/sources/paste', {
        title: title.value,
        author: author.value,
        text: text.value,
        duplicate_action: duplicate.value,
        source_id: versionSource.value,
      });
      open.value = false;
      await reload();
      await router.push(`/admin/library/${result.source.id}`);
    }, '资料已保存');
    return;
  }
  if (!files.value.length) {
    message.warning('请选择文件');
    return;
  }
  results.value = [];
  await run(async () => {
    for (const file of files.value) {
      const form = new FormData();
      form.set('file', file);
      if (files.value.length === 1 && title.value.trim()) form.set('title', title.value.trim());
      if (author.value.trim()) form.set('author', author.value.trim());
      form.set('duplicate_action', duplicate.value);
      if (versionSource.value) form.set('source_id', versionSource.value);
      try {
        const result = await upload<{ source: Entity }>('/sources/import', form);
        results.value.push({
          name: file.name,
          ok: true,
          message: '导入成功，可核对解析内容',
          id: result.source.id,
        });
      } catch (e) {
        results.value.push({ name: file.name, ok: false, message: errorText(e) });
      }
    }
    await reload();
  });
}
async function demo() {
  await run(async () => {
    await post('/demo/load');
    await reload();
  }, '原创演示资料已载入');
}
onMounted(() => {
  if (route.query.import) open.value = true;
});
</script>
<template>
  <PageHeader
    eyebrow="YOUR LIBRARY"
    title="资料与蒸馏"
    description="保存值得反复阅读的资料，让知识有清晰的来源。"
  >
    <n-button @click="demo" :loading="busy">
      <template #icon><Sparkles :size="16" /></template>
      原创演示资料
    </n-button>
    <n-button type="primary" @click="open = true">
      <template #icon><Plus :size="17" /></template>
      导入资料
    </n-button>
  </PageHeader>
  <div class="toolbar">
    <n-input v-model:value="q" class="search-field" placeholder="搜索标题或作者" clearable>
      <template #prefix><Search :size="15" /></template>
    </n-input>
    <n-select
      v-model:value="filter"
      :options="statuses"
      placeholder="全部状态"
      clearable
      style="width: 150px"
    />
    <span class="muted small">共 {{ sources.length }} 份资料</span>
  </div>
  <ResourceState
    :loading="loading"
    :error="error"
    :empty="!filtered.length"
    title="从第一份资料开始"
    description="支持 PDF、EPUB、TXT、Markdown、DOCX 和粘贴文本。扫描 PDF 可在导入后进行 OCR。"
    @retry="reload()"
  >
    <template #icon><BookOpen :size="34" :stroke-width="1.4" /></template>
    <template #action><n-button type="primary" @click="open = true">导入资料</n-button></template>
    <LibraryShelf :sources="filtered" area="admin" />
  </ResourceState>
  <n-modal
    v-model:show="open"
    preset="card"
    title="添加资料"
    style="width: 720px"
    :mask-closable="!busy"
  >
    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="file" tab="上传文件">
        <div
          class="upload-zone"
          :class="{ dragging }"
          @dragover.prevent="dragging = true"
          @dragleave="dragging = false"
          @drop.prevent="drop"
        >
          <UploadCloud :size="34" :stroke-width="1.3" />
          <h3>把资料拖到这里</h3>
          <p>PDF · EPUB · TXT · Markdown · DOCX</p>
          <n-button @click="fileInput?.click()">选择文件，可多选</n-button>
          <input
            ref="fileInput"
            type="file"
            multiple
            accept=".pdf,.epub,.txt,.md,.markdown,.docx"
            @change="pick"
            hidden
          />
        </div>
        <div class="selected-files" v-if="files.length">
          <div v-for="file in files" :key="file.name + file.size">
            <FileText :size="14" />
            {{ file.name }}
            <span>{{ (file.size / 1024 / 1024).toFixed(2) }} MB</span>
          </div>
        </div>
        <p class="field-hint">每个文件独立导入，失败不会影响其他文件。默认单文件上限 50 MB。</p>
      </n-tab-pane>
      <n-tab-pane name="text" tab="粘贴文本">
        <n-input
          v-model:value="text"
          type="textarea"
          placeholder="粘贴你的资料正文，个人备注请留在资料信息中。"
          :autosize="{ minRows: 8, maxRows: 15 }"
        />
      </n-tab-pane>
    </n-tabs>
    <div class="form-grid" style="margin-top: 20px">
      <n-form-item :label="tab === 'text' ? '标题（必填）' : '标题（单文件可选）'">
        <n-input v-model:value="title" :maxlength="100" placeholder="默认使用文件名" />
      </n-form-item>
      <n-form-item label="作者（可选）">
        <n-input v-model:value="author" placeholder="不确定可留空" />
      </n-form-item>
      <n-form-item label="重复资料处理">
        <n-select
          v-model:value="duplicate"
          :options="[
            { label: '提示重复，不覆盖已有资料', value: 'reject' },
            { label: '作为独立副本导入', value: 'copy' },
            { label: '作为已有资料的新版本', value: 'version' },
          ]"
        />
      </n-form-item>
      <n-form-item v-if="duplicate === 'version'" label="对应已有资料">
        <n-select
          v-model:value="versionSource"
          :options="sources.map((s) => ({ label: s.title, value: s.id }))"
          filterable
          placeholder="选择资料"
        />
      </n-form-item>
    </div>
    <n-alert type="info" :show-icon="false">
      基础解析在本地进行。OCR、蒸馏和后续 AI 分析会在你确认后发送到所选模型服务。
    </n-alert>
    <div v-if="results.length" class="import-results" aria-live="polite">
      <div v-for="r in results" :key="r.name" :class="{ failed: !r.ok }">
        <strong>{{ r.name }}</strong>
        <span>{{ r.message }}</span>
        <n-button
          v-if="r.id"
          size="tiny"
          @click="
            open = false;
            router.push('/admin/library/' + r.id);
          "
        >
          核对内容
        </n-button>
      </div>
    </div>
    <div class="modal-footer">
      <n-button @click="open = false" :disabled="busy">
        {{ results.length ? '完成' : '取消' }}
      </n-button>
      <n-button type="primary" :loading="busy" @click="importData">
        {{ busy ? '逐个导入中…' : '导入并预检查' }}
      </n-button>
    </div>
  </n-modal>
</template>
<style scoped>
.upload-zone {
  padding: 30px;
  border: 1px dashed var(--border);
  border-radius: 7px;
  text-align: center;
  background: var(--surface-subtle);
}
.upload-zone.dragging {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.upload-zone > svg {
  color: var(--accent);
  margin-bottom: 8px;
}
.upload-zone p {
  font-size: 11px;
  color: var(--muted);
  margin: 8px 0 16px;
}
.selected-files {
  margin-top: 12px;
  max-height: 160px;
  overflow: auto;
}
.selected-files > div {
  display: flex;
  gap: 8px;
  padding: 7px 0;
  font-size: 12px;
  align-items: center;
}
.selected-files span {
  margin-left: auto;
  color: var(--muted);
}
.import-results {
  margin-top: 16px;
  max-height: 200px;
  overflow: auto;
}
.import-results > div {
  padding: 8px 0;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  flex-wrap: wrap;
}
.import-results > div span {
  color: var(--accent);
}
.import-results > div.failed span {
  color: var(--danger);
}
</style>
