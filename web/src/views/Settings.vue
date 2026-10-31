<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import {
  Plus,
  Plug,
  ShieldCheck,
  Download,
  Upload,
  Settings2,
  KeyRound,
  SlidersHorizontal,
  CheckCircle2,
  Trash2,
  ExternalLink,
} from 'lucide-vue-next';
import { get, post, patch, remove, download, upload } from '../lib/api';
import { useAction, useConfirm } from '../lib/useData';
import { type Profile, textOf, typeLabels } from '../lib/types';
import ResearchConfig from '../components/ResearchConfig.vue';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
const props = defineProps<{ section: 'models' | 'general' | 'data' }>();
const pageTitle = computed(
  () => ({ models: '模型配置', general: '系统设置', data: '数据备份与恢复' })[props.section],
);
const { busy, run, message } = useAction();
const confirm = useConfirm();
const profiles = ref<Profile[]>([]),
  settings = ref<Record<string, any>>({ purpose_profiles: {} }),
  loading = ref(true),
  error = ref('');
const modelOpen = ref(false),
  editing = ref<Profile | null>(null),
  tested = ref<Record<string, any>>({});
const model = ref({
  name: '',
  protocol: 'openai_chat',
  base_url: '',
  model: '',
  api_key: '',
  enabled: true,
  stream: true,
  vision: false,
  json: true,
  embedding: false,
  context_tokens: 32768,
  max_tokens: 4096,
  temperature: 1,
});
const selectedDefault = ref<string | null>(null);
const purposeLabels = [
  { id: 'distill', label: '知识蒸馏' },
  { id: 'thought_distill', label: '女娲思想蒸馏' },
  { id: 'skill_generate', label: '独立 Skill 生成' },
  { id: 'skill_guidance', label: '独立实践引导' },
  { id: 'agent', label: '智能体生成' },
  { id: 'chat', label: '对话回复' },
  { id: 'summary', label: '讨论与成果总结' },
  { id: 'ocr', label: '扫描页 OCR' },
  { id: 'embedding', label: '在线向量检索' },
  { id: 'memory', label: '候选记忆提取' },
  { id: 'moderator', label: '动态主持选人' },
];
const enabledProfiles = computed(() => profiles.value.filter((p) => p.enabled));
const indexes = ref<any>(null);
const restoreFile = ref<HTMLInputElement | null>(null),
  preview = ref<any>(null),
  restoreResult = ref<any>(null),
  conflict = ref('copy'),
  includeOriginals = ref(false);
async function load() {
  loading.value = true;
  error.value = '';
  try {
    if (props.section === 'data') return;
    [profiles.value, settings.value] = await Promise.all([get('/profiles'), get('/settings')]);
    settings.value.purpose_profiles ||= {};
    selectedDefault.value = settings.value.default_profile_id || null;
    try {
      indexes.value = await get('/indexes');
    } catch {
      indexes.value = null;
    }
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
function newModel(preset?: string) {
  editing.value = null;
  model.value = {
    name: '',
    protocol: 'openai_chat',
    base_url: '',
    model: '',
    api_key: '',
    enabled: true,
    stream: true,
    vision: false,
    json: true,
    embedding: false,
    context_tokens: 32768,
    max_tokens: 4096,
    temperature: 1,
  };
  if (preset === 'deepseek')
    Object.assign(model.value, {
      name: 'DeepSeek Flash',
      base_url: 'https://api.deepseek.com',
      model: 'deepseek-flash',
      vision: true,
      context_tokens: 1000000,
    });
  if (preset === 'embedding')
    Object.assign(model.value, {
      name: '百炼 · 文本向量',
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      model: 'text-embedding-v4',
      embedding: true,
      stream: false,
      context_tokens: 8192,
    });
  if (preset === 'ollama')
    Object.assign(model.value, {
      name: '本机 Ollama',
      protocol: 'ollama',
      base_url: 'http://127.0.0.1:11434',
      model: '',
      stream: true,
    });
  modelOpen.value = true;
}
function editProfile(p: Profile) {
  editing.value = p;
  model.value = {
    name: p.name,
    protocol: p.protocol,
    base_url: p.base_url,
    model: p.model,
    api_key: '',
    enabled: p.enabled,
    stream: p.capabilities.stream ?? true,
    vision: !!p.capabilities.vision,
    json: p.capabilities.json ?? true,
    embedding: !!p.capabilities.embedding,
    context_tokens: p.capabilities.context_tokens || 32768,
    max_tokens: p.parameters.max_tokens || 4096,
    temperature: p.parameters.temperature ?? 1,
  };
  modelOpen.value = true;
}
async function saveModel() {
  if (!model.value.name.trim() || !model.value.base_url.trim() || !model.value.model.trim()) {
    message.warning('请填写名称、服务地址和模型名称');
    return;
  }
  await run(async () => {
    const m = model.value;
    const body = {
      name: m.name,
      protocol: m.protocol,
      base_url: m.base_url,
      model: m.model,
      enabled: m.enabled,
      capabilities: {
        stream: m.stream,
        vision: m.vision,
        json: m.json,
        embedding: m.embedding,
        context_tokens: m.context_tokens,
      },
      parameters: {
        ...(editing.value?.parameters || {}),
        max_tokens: m.max_tokens,
        temperature: m.temperature,
      },
      ...(m.api_key ? { api_key: m.api_key } : {}),
    };
    if (editing.value) await patch('/profiles/' + editing.value.id, body);
    else await post('/profiles', body);
    model.value.api_key = '';
    modelOpen.value = false;
    await load();
  }, '模型配置已保存，建议测试连接');
}
async function test(p: Profile) {
  await run(async () => {
    try {
      tested.value[p.id] = await post('/profiles/' + p.id + '/test');
    } finally {
      await load();
    }
  }, '连接测试已返回，请查看结果');
}
async function deleteProfile(p: Profile) {
  await confirm(
    '删除模型配置',
    `删除“${p.name}”后，使用它的任务与智能体需要重新配置，不会自动换到其他模型。`,
    () =>
      run(async () => {
        await remove('/profiles/' + p.id);
        await load();
      }, '模型配置已删除'),
  );
}
async function rebuildIndex() {
  await confirm(
    '重建检索索引',
    '将通过当前配置的在线向量模型重新处理资料，产生真实模型用量。已有索引不会与新模型向量混用。',
    () =>
      run(async () => {
        await post('/indexes/rebuild', { request_id: crypto.randomUUID() });
        message.info('重建任务已提交，可在任务中心查看进度。');
      }),
  );
}
async function saveSettings() {
  await run(async () => {
    settings.value = await patch('/settings', {
      ...settings.value,
      default_profile_id: selectedDefault.value,
    });
    settings.value.purpose_profiles ||= {};
  }, '本地设置已保存');
}
async function exportData() {
  if (includeOriginals.value) {
    await confirm(
      '包含原始文件导出',
      '资产包将包含所选工作区原始文件。请确认你有权在迁移目的地使用这些内容，并妥善保存导出包。',
      () =>
        run(() =>
          download('/export?kind=workspace&format=zip&originals=true', 'mindchime-workspace.zip'),
        ),
    );
  } else
    await run(() =>
      download('/export?kind=workspace&format=zip&originals=false', 'mindchime-workspace.zip'),
    );
}
async function previewImport(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  restoreResult.value = null;
  await run(async () => {
    const form = new FormData();
    form.set('file', file);
    preview.value = await upload('/imports/preview', form);
  });
}
async function restore() {
  if (!preview.value) return;
  await confirm(
    '恢复资产包',
    '将按预览和冲突策略恢复资产。缺失的模型配置和原文件需要在恢复后补齐。',
    () =>
      run(async () => {
        restoreResult.value = await post(`/imports/${preview.value.id}/restore`, {
          conflict: conflict.value,
        });
        preview.value = null;
      }, '资产包恢复完成'),
  );
}
</script>
<template>
  <PageHeader
    eyebrow="LOCAL WORKSPACE"
    :title="pageTitle"
    description="选择自己的模型服务，管理数据和本地运行边界。"
  />

  <section v-if="section === 'models'">
    <ResearchConfig />
    <ResourceState :loading="loading" :error="error" @retry="load">
      <div class="section-heading">
        <div>
          <div class="heading-with-help">
            <h2>独立模型配置</h2>
            <HelpTip label="独立模型配置说明">
              不同任务和智能体可使用不同服务。更换配置不会悄悄改变已确认任务。
            </HelpTip>
          </div>
        </div>
        <n-button type="primary" @click="newModel()">
          <Plus :size="15" />
          添加模型
        </n-button>
      </div>
      <div v-if="!profiles.length" class="setup-models">
        <div class="model-preset">
          <button @click="newModel('deepseek')">
            <Plug :size="24" />
            <strong>DeepSeek 官方</strong>
            <span>文本生成与图片理解</span>
          </button>
          <HelpTip label="模型预设说明" text="添加自己的 API 密钥" />
        </div>
        <div class="model-preset">
          <button @click="newModel('embedding')">
            <SlidersHorizontal :size="24" />
            <strong>在线检索模型</strong>
            <span>百炼 text-embedding-v4</span>
          </button>
          <HelpTip label="模型预设说明" text="独立可替换的向量配置" />
        </div>
        <div class="model-preset">
          <button @click="newModel('ollama')">
            <ShieldCheck :size="24" />
            <strong>本机模型服务</strong>
            <span>Ollama 原生接口</span>
          </button>
          <HelpTip label="模型预设说明" text="使用已运行的本机模型" />
        </div>
      </div>
      <div class="profile-list">
        <article
          v-for="p in profiles"
          :key="p.id"
          class="profile surface"
          :class="{ 'disabled-asset': !p.enabled }"
        >
          <div class="profile-top">
            <div class="profile-icon"><Plug :size="21" /></div>
            <div class="profile-info">
              <h3>
                {{ p.name }}
                <n-tag size="tiny" :bordered="false">{{ p.protocol }}</n-tag>
              </h3>
              <p>{{ p.model }} · {{ p.base_url }}</p>
            </div>
            <n-switch
              :value="p.enabled"
              @update:value="
                (enabled: boolean) =>
                  run(async () => {
                    await patch('/profiles/' + p.id, { enabled });
                    await load();
                  })
              "
              :aria-label="'启用' + p.name"
            />
          </div>
          <div class="profile-capabilities">
            <n-tag size="tiny" v-if="p.capabilities.vision" :bordered="false">图片输入</n-tag>
            <n-tag size="tiny" v-if="p.capabilities.embedding" :bordered="false">向量检索</n-tag>
            <n-tag size="tiny" v-if="p.capabilities.stream" :bordered="false">流式文本</n-tag>
            <n-tag
              size="tiny"
              :type="p.configured === false ? 'warning' : 'default'"
              :bordered="false"
            >
              {{ p.configured === false ? '尚未配置凭据' : '配置已保存' }}
            </n-tag>
            <n-tag
              size="tiny"
              :type="
                p.test_status === 'passed'
                  ? 'success'
                  : p.test_status === 'failed'
                    ? 'error'
                    : 'default'
              "
              :bordered="false"
            >
              {{
                p.test_status === 'passed'
                  ? '连接测试通过'
                  : p.test_status === 'failed'
                    ? '连接测试失败'
                    : '尚未测试'
              }}
            </n-tag>
            <span class="muted small">v{{ p.version }}</span>
            <HelpTip :label="p.name + '配置说明'">
              {{
                p.base_url.includes('127.0.0.1') || p.base_url.includes('localhost')
                  ? '本机地址'
                  : '内容将发送到外部服务'
              }}
              <p v-if="p.configuration_notice">{{ p.configuration_notice }}</p>
            </HelpTip>
          </div>
          <p v-if="p.last_test_error" class="error-text">{{ p.last_test_error }}</p>
          <n-alert
            v-if="tested[p.id]"
            :type="tested[p.id].ok === false || tested[p.id].status === 'failed' ? 'error' : 'info'"
            :show-icon="false"
            style="margin-top: 12px"
          >
            {{ textOf(tested[p.id].message || tested[p.id].error || tested[p.id]) }}
          </n-alert>
          <div class="profile-actions">
            <n-button size="small" @click="test(p)" :loading="busy">测试连接</n-button>
            <n-button size="small" @click="editProfile(p)">编辑配置</n-button>
            <n-button text size="small" type="error" @click="deleteProfile(p)">删除</n-button>
          </div>
        </article>
      </div>
      <div class="surface panel-pad section-spaced">
        <div class="heading-with-help">
          <h2>默认模型与任务分配</h2>
          <HelpTip label="默认模型与任务分配说明">
            除向量检索外，留空的用途会沿用默认模型。图片识别需选择支持图片输入的模型；向量检索必须配置对应能力。
          </HelpTip>
        </div>
        <n-form>
          <n-form-item label="默认生成模型">
            <n-select
              v-model:value="selectedDefault"
              :options="
                enabledProfiles
                  .filter((p) => !p.capabilities.embedding)
                  .map((p) => ({ label: `${p.name} · ${p.model}`, value: p.id }))
              "
              placeholder="选择默认模型"
              clearable
            />
          </n-form-item>
          <div class="form-grid">
            <n-form-item v-for="purpose in purposeLabels" :key="purpose.id" :label="purpose.label">
              <n-select
                v-model:value="settings.purpose_profiles[purpose.id]"
                :options="
                  enabledProfiles
                    .filter((p) =>
                      purpose.id === 'embedding'
                        ? p.capabilities.embedding
                        : purpose.id === 'ocr'
                          ? p.capabilities.vision
                          : !p.capabilities.embedding,
                    )
                    .map((p) => ({ label: p.name, value: p.id }))
                "
                clearable
                :placeholder="purpose.id === 'embedding' ? '选择在线向量模型' : '沿用默认模型'"
              />
            </n-form-item>
          </div>
        </n-form>
        <n-button type="primary" :loading="busy" @click="saveSettings">保存任务分配</n-button>
      </div>
    </ResourceState>
  </section>
  <section v-if="section === 'general'">
    <ResourceState :loading="loading" :error="error" @retry="load">
      <div class="surface panel-pad">
        <div class="heading-with-help">
          <h2>任务限制</h2>
          <HelpTip label="任务限制说明">
            上限是操作前可见的保护，不会通过静默截断内容来绕过。
            <br />
            <br />
            普通查看、编辑和导出不占 AI
            任务名额。关掉网页后，已确认的有限任务继续执行；停止本地业务服务会尽力取消在途调用。
          </HelpTip>
        </div>
        <n-form class="settings-form">
          <n-form-item label="单文件大小上限（MB）">
            <n-input-number v-model:value="settings.max_file_mb" :min="1" :max="500" />
          </n-form-item>
          <n-form-item label="单次蒸馏非空白字符上限">
            <n-input-number
              v-model:value="settings.max_distill_characters"
              :min="1000"
              :max="2000000"
              :step="10000"
            />
          </n-form-item>
          <n-form-item label="同时执行的业务任务数">
            <n-input-number v-model:value="settings.max_concurrent_tasks" :min="1" :max="8" />
          </n-form-item>
        </n-form>

        <n-button type="primary" :loading="busy" @click="saveSettings" style="margin-top: 20px">
          保存限制
        </n-button>
      </div>
      <section class="surface panel-pad section-spaced">
        <div class="section-heading">
          <h2>语义检索索引</h2>
          <n-button :loading="busy" @click="rebuildIndex">使用当前向量模型重建</n-button>
        </div>
        <HelpTip label="语义检索索引说明">
          索引按模型配置版本与维度分开保存。更换模型后请显式重建，不会混用不同模型的向量。
        </HelpTip>
        <div v-if="indexes?.indexes?.length" class="table-scroll">
          <table class="plain-table">
            <thead>
              <tr>
                <th>模型配置</th>
                <th>版本</th>
                <th>维度</th>
                <th>片段数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(index, i) in indexes.indexes" :key="i">
                <td>
                  {{ profiles.find((p) => p.id === index.profile_id)?.name || index.profile_id }}
                </td>
                <td>{{ index.profile_version }}</td>
                <td>{{ index.dimension }}</td>
                <td>{{ index.count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted small">
          暂无语义索引。
          <HelpTip label="创建语义索引说明" text="完成资料导入并配置向量模型后可创建。" />
        </p>
      </section>
    </ResourceState>
  </section>
  <section v-if="section === 'data'">
    <div class="grid-two">
      <section class="surface panel-pad">
        <Download :size="24" class="accent-icon" />
        <div class="heading-with-help">
          <h2 style="margin-top: 14px">导出工作区</h2>
          <HelpTip label="导出工作区说明">
            带走书架、知识卡、智能体、会话、成果和增强资产。结构化包可用于另一份本地实例恢复。
            <br />
            <br />
            默认不包含模型密钥、账号或付款信息。未选择原文件时，包内会说明缺失内容。
          </HelpTip>
        </div>
        <n-checkbox v-model:checked="includeOriginals">同时包含原始文件</n-checkbox>

        <n-button type="primary" @click="exportData" :loading="busy">导出 ZIP 资产包</n-button>
      </section>
      <section class="surface panel-pad">
        <Upload :size="24" class="accent-icon" />
        <div class="heading-with-help">
          <h2 style="margin-top: 14px">恢复资产包</h2>
          <HelpTip label="恢复资产包说明">
            先检查包内数量、同名或标识冲突与缺失依赖，再决定恢复方式。
            <br />
            <br />
            只接受 MindChime 结构化包。导入不会自动配置模型凭据，也不会静默覆盖现有数据。
          </HelpTip>
        </div>
        <input ref="restoreFile" type="file" accept=".zip" hidden @change="previewImport" />
        <n-button @click="restoreFile?.click()" :loading="busy">选择 ZIP 并预览</n-button>
      </section>
    </div>
    <section class="surface panel-pad section-spaced" v-if="preview">
      <h2>恢复预览</h2>
      <div class="chip-row" style="margin: 16px 0">
        <n-tag v-for="(count, kind) in preview.counts" :key="kind" :bordered="false">
          {{ typeLabels[String(kind)] || kind }} {{ count }}
        </n-tag>
      </div>
      <p class="muted small">
        {{ preview.includes_originals ? '包含原始文件' : '不包含原始文件' }} ·
        {{ preview.conflicts.length }} 项标识冲突 · {{ preview.missing.length }} 项缺失依赖
      </p>
      <n-alert v-if="preview.missing.length" type="warning" style="margin-top: 16px">
        存在缺失依赖，恢复后相关资产可能不可用，需修复后才能继续使用。
      </n-alert>
      <div class="table-scroll" v-if="preview.conflicts.length">
        <table class="plain-table" style="margin-top: 16px">
          <thead>
            <tr>
              <th>冲突对象</th>
              <th>类型</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in preview.conflicts" :key="c.id">
              <td>{{ c.title }}</td>
              <td>{{ typeLabels[c.kind] || c.kind }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <n-form-item label="冲突处理" style="margin-top: 20px">
        <n-select
          v-model:value="conflict"
          :options="[
            { label: '创建独立副本并重建关联', value: 'copy' },
            { label: '跳过已有标识，保留现有资产', value: 'skip' },
          ]"
          style="max-width: 420px"
        />
      </n-form-item>
      <n-button type="primary" @click="restore" :loading="busy">确认恢复</n-button>
    </section>
    <n-alert v-if="restoreResult" type="success" style="margin-top: 24px">
      恢复完成。{{ textOf(restoreResult.counts || restoreResult.imported || restoreResult) }}
    </n-alert>
  </section>

  <n-modal
    v-if="section === 'models'"
    v-model:show="modelOpen"
    preset="card"
    :title="editing ? '编辑模型配置' : '添加模型配置'"
    style="width: 700px"
  >
    <n-form>
      <div class="form-grid">
        <n-form-item label="配置名称">
          <n-input v-model:value="model.name" placeholder="方便辨认的名称" />
        </n-form-item>
        <n-form-item label="接口协议">
          <n-select
            v-model:value="model.protocol"
            :options="[
              { label: 'OpenAI Chat 兼容', value: 'openai_chat' },
              { label: 'OpenAI Responses', value: 'openai_responses' },
              { label: 'Anthropic Messages', value: 'anthropic' },
              { label: 'Ollama 原生', value: 'ollama' },
            ]"
          />
        </n-form-item>
      </div>
      <n-form-item label="服务地址（Base URL）">
        <n-input v-model:value="model.base_url" placeholder="https://api.example.com/v1" />
      </n-form-item>
      <n-form-item label="模型名称">
        <n-input v-model:value="model.model" placeholder="服务实际接受的模型 ID" />
      </n-form-item>
      <n-form-item :label="editing ? 'API 密钥（留空保留现有密钥）' : 'API 密钥'">
        <n-input
          v-model:value="model.api_key"
          type="password"
          show-password-on="click"
          autocomplete="new-password"
          placeholder="只交给独立 AI 服务保存"
        />
      </n-form-item>
      <n-form-item label="模型能力声明">
        <div class="chip-row">
          <n-checkbox v-model:checked="model.stream">流式文本</n-checkbox>
          <n-checkbox v-model:checked="model.json">JSON 输出</n-checkbox>
          <n-checkbox v-model:checked="model.vision">图片输入</n-checkbox>
          <n-checkbox v-model:checked="model.embedding">文本向量</n-checkbox>
        </div>
      </n-form-item>
      <div class="form-grid">
        <n-form-item label="上下文 Token 上限">
          <n-input-number v-model:value="model.context_tokens" :min="1024" :step="1024" />
        </n-form-item>
        <n-form-item label="单次最大输出 Token">
          <n-input-number v-model:value="model.max_tokens" :min="128" :step="512" />
        </n-form-item>
        <n-form-item label="Temperature（服务支持时生效）">
          <n-input-number v-model:value="model.temperature" :min="0" :max="2" :step="0.1" />
        </n-form-item>
      </div>
    </n-form>
    <HelpTip label="模型与系统说明">
      能力声明仍需实际测试。平台不会自动改用其他服务，也不会把未配置的模型伪装成可用。
    </HelpTip>
    <div class="modal-footer">
      <n-button
        @click="
          modelOpen = false;
          model.api_key = '';
        "
      >
        取消
      </n-button>
      <n-button type="primary" :loading="busy" @click="saveModel">保存配置</n-button>
    </div>
  </n-modal>
</template>
<style scoped>
.model-preset {
  position: relative;
}
.model-preset > button {
  width: 100%;
  height: 100%;
}
.model-preset > :deep(.help-tip) {
  position: absolute;
  top: 8px;
  right: 8px;
}

.setup-models {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.setup-models button {
  text-align: left;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 24px;
  color: var(--text);
  cursor: pointer;
}
.setup-models button:hover {
  border-color: var(--accent);
}
.setup-models svg,
.accent-icon {
  color: var(--accent);
}
.setup-models strong,
.setup-models span,
.setup-models small {
  display: block;
}
.setup-models strong {
  font-size: 16px;
  margin: 16px 0 8px;
}
.setup-models span {
  font-size: 12px;
  color: var(--text-secondary);
}
.setup-models small {
  font-size: 10px;
  color: var(--muted);
  margin-top: 12px;
}
.profile-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.profile {
  padding: 22px;
}
.profile-top {
  display: flex;
  align-items: center;
  gap: 12px;
}
.profile-icon {
  width: 38px;
  height: 38px;
  background: var(--accent-soft);
  display: grid;
  place-items: center;
  color: var(--accent);
  border-radius: 7px;
  flex-shrink: 0;
}
.profile-info {
  flex: 1;
  min-width: 0;
}
.profile-info h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.profile-info p {
  font-size: 10px;
  color: var(--muted);
  margin-top: 5px;
  overflow-wrap: anywhere;
}
.profile-capabilities {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 16px 0;
}
.profile-actions {
  border-top: 1px solid var(--border);
  padding-top: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.profile-actions > *:last-child {
  margin-left: auto;
}
.settings-form {
  max-width: 540px;
  margin-top: 22px;
}
@media (max-width: 1200px) {
  .profile-list {
    grid-template-columns: 1fr;
  }
  .setup-models {
    grid-template-columns: 1fr;
  }
  .setup-models button {
    padding: 18px;
  }
}
</style>
