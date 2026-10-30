<script setup lang="ts">
import { isAdmin } from '../lib/auth';
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  Plus,
  Search,
  Send,
  MessagesSquare,
  MessageSquare,
  Users,
  Settings2,
  Download,
  Bookmark,
  Copy,
  Quote,
  ThumbsUp,
  Flag,
  NotebookPen,
  MoreHorizontal,
  Play,
  Pause,
  Square,
  Brain,
  Archive,
  Trash2,
  RefreshCw,
} from 'lucide-vue-next';
import { get, post, patch, remove, download, events } from '../lib/api';
import { useResource, useAction, useConfirm } from '../lib/useData';
import {
  type Entity,
  type Reference,
  textOf,
  dateText,
  requestId,
  liveJobStates,
} from '../lib/types';
import ResourceState from '../components/ResourceState.vue';
import MarkdownText from '../components/MarkdownText.vue';
import StatusBadge from '../components/StatusBadge.vue';
import EvidenceDrawer from '../components/EvidenceDrawer.vue';
import ReferenceLinks from '../components/ReferenceLinks.vue';
import JobStrip from '../components/JobStrip.vue';
const route = useRoute(),
  router = useRouter();
const { data: conversations, reload: reloadList } = useResource(
  () => get<Entity[]>('/conversations'),
  [],
  10000,
);
const agents = ref<Entity[]>([]),
  allCards = ref<Entity[]>([]);
const sharedCards = ref<string[]>([]),
  generalOverrides = ref<Record<string, boolean>>({}),
  memoryAgent = ref<string | null>(null),
  selectionMode = ref(false),
  selectedMessages = ref<string[]>([]);
const detail = ref<any>(null),
  loading = ref(false),
  error = ref('');
const id = computed(() => String(route.params.id || ''));
const { busy, run, message } = useAction();
const confirm = useConfirm();
const q = ref(''),
  input = ref(''),
  recipients = ref<string[]>([]),
  chatScroll = ref<HTMLElement | null>(null);
const createOpen = ref(false),
  createTitle = ref(''),
  createMode = ref('single'),
  createAgents = ref<string[]>([]),
  background = ref('');
const discussionOpen = ref(false),
  discussion = ref({
    topic: '',
    background: '',
    mode: 'ordered',
    rounds: 3,
    max_speeches: 9,
    max_minutes: 20,
    summary: true,
    goal: 'understand',
  });
const settingsOpen = ref(false),
  settingsTitle = ref(''),
  settingsBackground = ref(''),
  settingsAgents = ref<string[]>([]);
const evidenceOpen = ref(false),
  evidence = ref<Reference | null>(null);
const saveOpen = ref(false),
  saveText = ref(''),
  saveTitle = ref(''),
  saveMessageIds = ref<string[]>([]),
  saveType = ref('note');
const streamText = ref(''),
  streamName = ref(''),
  streamStep = ref('');
let stopEvents: (() => void) | undefined;
let timer: ReturnType<typeof setInterval> | undefined;
let mounted = true;
const showArchived = ref(false);
const visibleConversations = computed(() =>
  conversations.value.filter(
    (c) =>
      (!q.value || c.title.includes(q.value)) && (showArchived.value || c.status !== 'archived'),
  ),
);
const current = computed<Entity | null>(() => detail.value?.conversation || null);
const messages = computed<Entity[]>(() => detail.value?.messages || []);
const activeJob = computed<Entity | undefined>(() =>
  (detail.value?.jobs || []).find((j: Entity) => !['completed', 'cancelled'].includes(j.status)),
);
const running = computed(() => !!activeJob.value && liveJobStates.includes(activeJob.value.status));
const participants = computed(() => {
  const ids =
    current.value?.data.agent_ids || current.value?.data.members?.map((m: any) => m.agent_id) || [];
  return ids
    .map(
      (id: string) =>
        agents.value.find((a) => a.id === id) || current.value?.data.agent_snapshots?.[id],
    )
    .filter(Boolean) as Entity[];
});
const isGroup = computed(() => current.value?.data.mode === 'group');
const memberOptions = computed(() =>
  participants.value.map((a) => ({ label: a.title, value: a.id })),
);
async function refresh(quiet = false) {
  if (!id.value) {
    detail.value = null;
    return;
  }
  if (!quiet) loading.value = true;
  try {
    const d = await get('/conversations/' + id.value);
    if (mounted && id.value === d.conversation?.id) {
      detail.value = d;
      error.value = '';
      if (!d.jobs?.some((j: Entity) => liveJobStates.includes(j.status))) {
        streamText.value = '';
        streamName.value = '';
      }
    }
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
function bindEvents() {
  stopEvents?.();
  streamText.value = '';
  if (!id.value) return;
  stopEvents = events('conversation:' + id.value, (event: any) => {
    const d = event.data || event;
    const type = event.event || event.type;
    if (type === 'text_delta' || (d.text && d.agent_id)) {
      if (d.step_key && d.step_key !== streamStep.value) {
        streamText.value = '';
        streamStep.value = d.step_key;
      }
      streamText.value += d.text || '';
      streamName.value =
        d.agent_name || participants.value.find((a) => a.id === d.agent_id)?.title || '智能体';
      void scrollBottom();
    } else {
      if (['message', 'completed', 'failed', 'cancelled'].includes(type)) {
        streamText.value = '';
        streamStep.value = '';
      }
      void refresh(true);
    }
  });
}
async function scrollBottom() {
  await nextTick();
  if (chatScroll.value) chatScroll.value.scrollTop = chatScroll.value.scrollHeight;
}
watch(
  id,
  async () => {
    await refresh();
    recipients.value = [];
    bindEvents();
    await scrollBottom();
  },
  { immediate: true },
);
watch(() => messages.value.length, scrollBottom);
onMounted(async () => {
  await run(async () => {
    [agents.value, allCards.value] = await Promise.all([get('/agents'), get('/cards')]);
  });
  timer = setInterval(() => void refresh(true), 2500);
});
onUnmounted(() => {
  mounted = false;
  stopEvents?.();
  clearInterval(timer);
});
async function create() {
  if (!createTitle.value.trim() || !createAgents.value.length) {
    message.warning('请填写名称并选择智能体');
    return;
  }
  if (
    createMode.value === 'group' &&
    (createAgents.value.length < 2 || createAgents.value.length > 6)
  ) {
    message.warning('群聊需要 2–6 位成员');
    return;
  }
  await run(async () => {
    const c = await post('/conversations', {
      title: createTitle.value,
      data: { mode: createMode.value, agent_ids: createAgents.value, background: background.value },
    });
    createOpen.value = false;
    await reloadList();
    await router.push('/chat/' + c.id);
  }, '对话已创建');
}
async function send() {
  if (!input.value.trim() || !id.value) return;
  const text = input.value;
  await run(
    async () => {
      await post(
        '/conversations/' + id.value + (running.value ? '/interject' : '/messages'),
        running.value
          ? { text }
          : {
              text,
              agent_ids: recipients.value.length ? recipients.value : undefined,
              request_id: requestId(),
            },
      );
      input.value = '';
      await refresh(true);
      await scrollBottom();
    },
    running.value ? '已请求暂停后插入；暂停后由你决定继续' : undefined,
  );
}
async function startDiscussion() {
  if (!discussion.value.topic.trim()) {
    message.warning('请填写具体议题');
    return;
  }
  await run(async () => {
    await post(`/conversations/${id.value}/discussions`, {
      ...discussion.value,
      request_id: requestId(),
    });
    discussionOpen.value = false;
    await refresh(true);
  }, '已按确认的计划启动讨论');
}
function openSettings() {
  settingsTitle.value = current.value?.title || '';
  settingsBackground.value = current.value?.data.background || '';
  settingsAgents.value = [...(current.value?.data.agent_ids || [])];
  sharedCards.value = [...(current.value?.data.shared_card_ids || [])];
  generalOverrides.value = { ...(current.value?.data.general_knowledge_overrides || {}) };
  memoryAgent.value = participants.value[0]?.id || null;
  settingsOpen.value = true;
}
async function saveSettings() {
  await run(async () => {
    await patch('/conversations/' + id.value, {
      title: settingsTitle.value,
      data: {
        background: settingsBackground.value,
        shared_card_ids: sharedCards.value,
        ...(isAdmin.value ? { general_knowledge_overrides: generalOverrides.value } : {}),
      },
    });
    if (JSON.stringify(settingsAgents.value) !== JSON.stringify(current.value?.data.agent_ids))
      await post('/conversations/' + id.value + '/members', { agent_ids: settingsAgents.value });
    settingsOpen.value = false;
    await refresh(true);
    await reloadList();
  }, '对话设置已保存');
}
async function switchVersion(a: Entity) {
  await confirm(
    '切换智能体版本',
    `后续消息将使用“${a.title}”当前版本 v${a.version}，此前消息保持不变。`,
    () =>
      run(async () => {
        await post(`/conversations/${id.value}/switch-version`, {
          agent_id: a.id,
          version: a.version,
        });
        await refresh(true);
      }, '已记录版本切换'),
  );
}
function saveSelected() {
  const chosen = messages.value.filter((m) => selectedMessages.value.includes(m.id));
  if (!chosen.length) {
    message.warning('请先选择消息');
    return;
  }
  saveText.value = chosen
    .map(
      (m) =>
        `### ${m.data.speaker_name || m.data.agent_name || '你'}\n\n${m.data.content || m.data.text}`,
    )
    .join('\n\n');
  saveTitle.value = (current.value?.title || '对话') + ' · 选段';
  saveMessageIds.value = chosen.map((m) => m.id);
  saveType.value = 'note';
  saveOpen.value = true;
}
async function generateArtifact() {
  await confirm(
    'AI 整理为成果',
    '将使用所选消息（未选则使用整场会话）生成一份新成果，会产生模型调用。',
    () =>
      run(async () => {
        await post('/artifacts/generate', {
          conversation_id: id.value,
          message_ids: selectedMessages.value.length ? selectedMessages.value : undefined,
          type: '问题分析',
          request_id: requestId(),
        });
        message.success('成果整理任务已提交，可到任务中心查看');
      }),
  );
}
function saveMessage(m: Entity) {
  saveText.value = textOf(m.data.content || m.data.text);
  saveTitle.value = m.title || '对话笔记';
  saveMessageIds.value = [m.id];
  saveType.value = 'note';
  saveOpen.value = true;
}
async function saveArtifact() {
  await run(async () => {
    const selected = messages.value.filter((m) => saveMessageIds.value.includes(m.id));
    await post('/artifacts', {
      title: saveTitle.value,
      data: {
        type: saveType.value,
        content: saveText.value,
        conversation_id: id.value,
        message_ids: saveMessageIds.value,
        references: selected.flatMap((m) => m.data.references || []),
        source_ids: [
          ...new Set(
            selected.flatMap((m) => (m.data.references || []).map((r: Reference) => r.source_id)),
          ),
        ],
      },
    });
    saveOpen.value = false;
  }, '已保存到我的成果');
}
async function feedback(m: Entity, type: string) {
  await run(
    () => post('/messages/' + m.id + '/feedback', { type }),
    '反馈已保存，仅关联当前个人消息',
  );
}
async function favorite(m: Entity) {
  await run(
    async () => {
      await post('/messages/' + m.id + '/favorite', { favorite: !m.data.favorite });
      await refresh(true);
    },
    m.data.favorite ? '已取消收藏' : '已收藏',
  );
}
async function copy(m: Entity) {
  await run(() => navigator.clipboard.writeText(textOf(m.data.content || m.data.text)), '已复制');
}
async function regenerate() {
  const lastUser = [...messages.value].reverse().find((m) => m.data.role === 'user');
  if (!lastUser) return;
  await confirm('重新生成回复', '这是一次新的模型请求，会再次产生模型用量。旧回复仍保留。', () =>
    run(async () => {
      await post('/conversations/' + id.value + '/messages', {
        text: lastUser.data.content || lastUser.data.text,
        agent_ids: recipients.value.length ? recipients.value : undefined,
        request_id: requestId(),
      });
      await refresh(true);
    }),
  );
}
async function summarize() {
  await confirm('生成讨论总结', '总结将根据实际发言生成，是一次新的模型请求。', () =>
    run(async () => {
      await post('/conversations/' + id.value + '/summary', { request_id: requestId() });
      await refresh(true);
    }, '总结任务已提交'),
  );
}
async function archive() {
  await run(async () => {
    await patch('/conversations/' + id.value, {
      status: current.value?.status === 'archived' ? 'active' : 'archived',
    });
    await reloadList();
    await router.push('/chat');
  }, '对话归档状态已更新');
}
async function del() {
  await confirm('删除对话', '删除当前对话及其消息，已保存的独立成果不会自动删除。', () =>
    run(async () => {
      await remove('/conversations/' + id.value);
      await reloadList();
      await router.push('/chat');
    }, '对话已删除'),
  );
}
</script>
<template>
  <div class="chat-workspace">
    <aside class="conversation-sidebar">
      <div class="conversation-heading">
        <h1>对话空间</h1>
        <n-button quaternary circle size="small" @click="createOpen = true" aria-label="新建对话">
          <Plus :size="19" />
        </n-button>
      </div>
      <n-input v-model:value="q" size="small" placeholder="查找对话" clearable>
        <template #prefix><Search :size="14" /></template>
      </n-input>
      <n-checkbox v-model:checked="showArchived" style="margin: 10px 0">包含已归档对话</n-checkbox>
      <div class="conversation-list">
        <RouterLink
          v-for="c in visibleConversations"
          :key="c.id"
          :to="'/chat/' + c.id"
          class="conversation-item"
          :class="{ active: c.id === id }"
        >
          <component :is="c.data.mode === 'single' ? MessageSquare : Users" :size="16" />
          <div>
            <strong>{{ c.title }}</strong>
            <small>{{ dateText(c.updated_at) }}</small>
          </div>
        </RouterLink>
        <p v-if="!visibleConversations.length" class="muted small" style="padding: 20px 0">
          还没有对话。创建一个智能体后，就可以开始。
        </p>
      </div>
      <n-button class="full-width" @click="createOpen = true">
        <Plus :size="14" />
        新建对话
      </n-button>
    </aside>
    <section class="chat-main">
      <ResourceState
        v-if="!id"
        :empty="true"
        title="一个问题，多种看见。"
        description="带上真实的背景与限制，让不同的思想互相回应。你的资料和对话保存在本地。"
      >
        <template #icon><MessagesSquare :size="42" :stroke-width="1.2" /></template>
        <template #action>
          <n-button type="primary" @click="createOpen = true">开始一场对话</n-button>
        </template>
      </ResourceState>
      <template v-else>
        <div class="chat-heading">
          <div>
            <h2>{{ current?.title || '加载对话…' }}</h2>
            <div class="chat-members">
              <span v-for="a in participants" :key="a.id">{{ a.title }}</span>
              <span v-if="current?.data.trial" class="trial-label">草稿试聊</span>
            </div>
          </div>
          <div class="inline-actions">
            <n-button
              v-if="isGroup"
              size="small"
              type="primary"
              :disabled="!!activeJob"
              @click="
                discussion.background = current?.data.background || '';
                discussionOpen = true;
              "
            >
              <Play :size="13" />
              开始讨论
            </n-button>
            <n-button
              size="small"
              @click="
                selectionMode = !selectionMode;
                selectedMessages = [];
              "
            >
              {{ selectionMode ? '取消选段' : '选择消息' }}
            </n-button>
            <n-button size="small" @click="openSettings" aria-label="对话设置">
              <Settings2 :size="16" />
            </n-button>
            <n-button
              size="small"
              @click="run(() => download(`/export?kind=conversation&id=${id}&format=markdown`))"
              aria-label="导出对话"
            >
              <Download :size="16" />
            </n-button>
          </div>
        </div>
        <div v-if="activeJob" class="chat-job">
          <JobStrip :job="activeJob" @changed="refresh(true)" />
        </div>
        <div v-if="selectionMode" class="selected-message-tools">
          <span>已选 {{ selectedMessages.length }} 条</span>
          <n-button
            size="tiny"
            @click="
              selectedMessages = messages.filter((m) => m.data.role !== 'system').map((m) => m.id)
            "
          >
            全选
          </n-button>
          <n-button size="tiny" :disabled="!selectedMessages.length" @click="saveSelected">
            保存选段
          </n-button>
          <n-button size="tiny" :disabled="!!activeJob" @click="generateArtifact">
            AI 整理成果
          </n-button>
        </div>
        <div ref="chatScroll" class="message-scroll">
          <ResourceState :loading="loading" :error="error" @retry="refresh()">
            <div v-if="!messages.length" class="chat-intro">
              <span class="eyebrow">准备好听听不同的想法</span>
              <h2>
                {{ isGroup ? '发一个问题，或开启有限轮次的圆桌。' : '从你正在思考的问题开始。' }}
              </h2>
              <HelpTip
                label="对话背景说明"
                text="背景越清楚，讨论越有针对性。资料不足时，智能体应明确告诉你。"
              />
            </div>
            <article
              v-for="m in messages"
              :id="'message-' + m.id"
              :key="m.id"
              class="chat-message"
              :class="{
                'from-user': m.data.role === 'user',
                'system-message': m.data.role === 'system',
              }"
            >
              <template v-if="m.data.role === 'system'">
                <span>{{ textOf(m.data.content || m.data.text) }}</span>
              </template>
              <template v-else>
                <n-checkbox
                  v-if="selectionMode"
                  :checked="selectedMessages.includes(m.id)"
                  @update:checked="
                    selectedMessages = $event
                      ? [...selectedMessages, m.id]
                      : selectedMessages.filter((id) => id !== m.id)
                  "
                  :aria-label="'选择消息 ' + m.id"
                />
                <div class="message-avatar" :class="{ user: m.data.role === 'user' }">
                  {{
                    m.data.role === 'user'
                      ? '你'
                      : String(m.data.agent_name || m.data.speaker_name || m.title || '思').slice(
                          0,
                          1,
                        )
                  }}
                </div>
                <div class="message-body">
                  <div class="message-meta">
                    <strong>
                      {{
                        m.data.role === 'user'
                          ? '你'
                          : m.data.agent_name || m.data.speaker_name || m.title || '智能体'
                      }}
                    </strong>
                    <span v-if="m.data.agent_version">v{{ m.data.agent_version }}</span>
                    <span>{{ dateText(m.created_at) }}</span>
                    <n-tag
                      v-if="m.status === 'incomplete' || m.data.incomplete"
                      size="tiny"
                      type="warning"
                    >
                      未完成
                    </n-tag>
                    <n-tag v-if="m.data.favorite" size="tiny" :bordered="false">已收藏</n-tag>
                  </div>
                  <div v-if="m.data.response_to?.length" class="response-links">
                    <a
                      v-for="target in m.data.response_to"
                      :key="target"
                      :href="'#message-' + target"
                    >
                      回应
                      {{ messages.find((v) => v.id === target)?.data.speaker_name || '前文观点' }}
                      ↗
                    </a>
                  </div>
                  <n-tag
                    v-if="m.data.basis"
                    size="tiny"
                    :bordered="false"
                    style="margin-bottom: 10px"
                  >
                    {{ m.data.basis }}
                  </n-tag>
                  <MarkdownText :text="textOf(m.data.content || m.data.text)" />
                  <ReferenceLinks
                    v-if="m.data.references?.length"
                    :references="m.data.references"
                    @open="
                      (reference) => {
                        evidence = reference;
                        evidenceOpen = true;
                      }
                    "
                  />
                  <p v-if="m.data.context_summarized || m.data.context_notice" class="muted small">
                    当前回复使用了阶段摘要，原始消息仍保留。
                  </p>
                  <div class="message-actions">
                    <button @click="copy(m)" aria-label="复制消息"><Copy :size="13" /></button>
                    <button
                      @click="favorite(m)"
                      :aria-label="m.data.favorite ? '取消收藏' : '收藏消息'"
                    >
                      <Bookmark :size="13" />
                    </button>
                    <button @click="saveMessage(m)">
                      <NotebookPen :size="13" />
                      保存成果
                    </button>
                    <template v-if="m.data.role !== 'user'">
                      <button @click="feedback(m, 'helpful')" aria-label="有帮助">
                        <ThumbsUp :size="13" />
                      </button>
                      <n-dropdown
                        trigger="click"
                        :options="[
                          { label: '来源不符', key: 'source_mismatch' },
                          { label: '错误归因', key: 'misattribution' },
                          { label: '没有回答问题', key: 'off_topic' },
                        ]"
                        @select="(type: string) => feedback(m, String(type))"
                      >
                        <button aria-label="反馈问题"><Flag :size="13" /></button>
                      </n-dropdown>
                    </template>
                  </div>
                </div>
              </template>
            </article>
            <article v-if="streamText" class="chat-message">
              <div class="message-avatar">{{ streamName.slice(0, 1) }}</div>
              <div class="message-body">
                <div class="message-meta">
                  <strong>{{ streamName }}</strong>
                  <span>正在生成…</span>
                </div>
                <MarkdownText :text="streamText" />
              </div>
            </article>
            <div v-if="running && !streamText" class="generating-hint">
              <span class="pulse-dot" />
              正在处理，请稍候。你可以暂停或结束。
            </div>
          </ResourceState>
        </div>
        <div class="chat-composer">
          <div class="composer-tools">
            <n-select
              v-if="isGroup"
              v-model:value="recipients"
              multiple
              clearable
              size="small"
              :options="memberOptions"
              placeholder="@ 全部成员，按顺序各回复一次"
              style="max-width: 410px"
              :disabled="!!activeJob"
            />
            <div v-else class="muted small">默认依据绑定知识回答</div>
            <div class="inline-actions">
              <n-button
                text
                size="tiny"
                :disabled="!messages.length || !!activeJob"
                @click="regenerate"
              >
                <RefreshCw :size="12" />
                重新生成
              </n-button>
              <n-button
                text
                size="tiny"
                :disabled="!messages.length || !!activeJob"
                @click="summarize"
              >
                生成总结
              </n-button>
            </div>
          </div>
          <div class="input-box">
            <n-input
              v-model:value="input"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 6 }"
              :bordered="false"
              :placeholder="running ? '补充意见，将在当前发言完成后插入…' : '说说你的问题与背景…'"
              @keydown="
                (e: KeyboardEvent) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    send();
                  }
                }
              "
            />
            <div class="input-footer">
              <HelpTip
                label="发送与快捷键说明"
                text="⌘ / Ctrl + Enter 发送；外部模型调用会产生服务商用量。"
              />
              <n-button
                type="primary"
                :disabled="!input.trim() || (!!activeJob && !running)"
                :loading="busy"
                @click="send"
              >
                <Send :size="14" />
                {{ running ? '暂停后插入' : '发送' }}
              </n-button>
            </div>
          </div>
          <HelpTip label="使用说明">AI 的归纳不等于事实已核实。重要观点可以展开来源核对。</HelpTip>
        </div>
      </template>
    </section>
  </div>
  <n-modal v-model:show="createOpen" preset="card" title="新建对话" style="width: 600px">
    <n-form>
      <n-form-item label="名称">
        <n-input v-model:value="createTitle" :maxlength="100" placeholder="给这次思考起个名字" />
      </n-form-item>
      <n-form-item label="类型">
        <n-radio-group v-model:value="createMode" @update:value="createAgents = []">
          <n-radio-button value="single">单个智能体</n-radio-button>
          <n-radio-button value="group">多智能体群聊</n-radio-button>
        </n-radio-group>
      </n-form-item>
      <n-form-item label="参与智能体（选择顺序就是默认发言顺序）">
        <n-select
          v-model:value="createAgents"
          multiple
          :max-tag-count="6"
          :options="
            agents
              .filter((a) => ['active', 'ready', 'available', 'incomplete'].includes(a.status))
              .map((a) => ({ label: a.title, value: a.id }))
          "
          placeholder="选择已发布的可用智能体"
          @update:value="
            (ids: string[]) => {
              if (createMode === 'single' && ids.length > 1) createAgents = [ids[ids.length - 1]];
            }
          "
        />
      </n-form-item>
      <n-form-item label="我的背景与目标（只用于当前会话）">
        <n-input
          v-model:value="background"
          type="textarea"
          :maxlength="5000"
          :autosize="{ minRows: 3, maxRows: 6 }"
        />
      </n-form-item>
    </n-form>
    <div class="modal-footer">
      <n-button @click="createOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="create">创建对话</n-button>
    </div>
  </n-modal>
  <n-modal v-model:show="discussionOpen" preset="card" title="本次讨论计划" style="width: 650px">
    <n-form>
      <n-form-item label="具体议题">
        <n-input
          v-model:value="discussion.topic"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
          placeholder="希望这些观点共同讨论什么？"
        />
      </n-form-item>
      <n-form-item label="背景与现实限制">
        <n-input v-model:value="discussion.background" type="textarea" :maxlength="5000" />
      </n-form-item>
      <n-form-item label="本次目标">
        <n-select
          v-model:value="discussion.goal"
          :options="[
            { label: '理解不同观点', value: 'understand' },
            { label: '检验一个主张', value: 'challenge_claim' },
            { label: '形成行动方案', value: 'action_plan' },
          ]"
        />
      </n-form-item>
      <n-form-item label="讨论模式">
        <n-select
          v-model:value="discussion.mode"
          :options="[
            { label: '有序圆桌：按顺序回应已有观点', value: 'ordered' },
            { label: '交叉质疑：检查依据、前提与反例', value: 'challenge' },
            { label: '自由讨论：主持动态选人，逐个发言', value: 'dynamic' },
          ]"
        />
      </n-form-item>
      <div class="form-grid">
        <n-form-item v-if="discussion.mode !== 'dynamic'" label="最多轮次">
          <n-input-number v-model:value="discussion.rounds" :min="1" :max="10" />
        </n-form-item>
        <n-form-item v-else label="最多成员发言数">
          <n-input-number v-model:value="discussion.max_speeches" :min="1" :max="60" />
        </n-form-item>
        <n-form-item label="最长时间（分钟）">
          <n-input-number v-model:value="discussion.max_minutes" :min="1" :max="120" />
        </n-form-item>
      </div>
      <n-form-item label="结束后生成总结">
        <n-switch v-model:value="discussion.summary" />
      </n-form-item>
    </n-form>
    <div class="discussion-preview">
      <strong>{{ participants.map((a) => a.title).join(' → ') }}</strong>
      <p>
        最多
        {{
          discussion.mode === 'dynamic'
            ? discussion.max_speeches
            : participants.length * discussion.rounds
        }}
        次成员发言{{ discussion.summary ? '，另加 1 次总结' : '' }}。{{
          discussion.mode === 'dynamic' ? '动态主持另有有限的选人调用。' : ''
        }}
      </p>
      <HelpTip
        label="讨论执行说明"
        text="内容将发送到各成员选定的模型；关掉网页后继续至既定上限。立即结束不会自动追加总结。"
      />
    </div>
    <div class="modal-footer">
      <n-button @click="discussionOpen = false">返回</n-button>
      <n-button type="primary" :loading="busy" @click="startDiscussion">确认开始讨论</n-button>
    </div>
  </n-modal>
  <n-drawer v-model:show="settingsOpen" :width="480">
    <n-drawer-content title="当前对话设置" closable>
      <n-alert v-if="activeJob" type="warning" :show-icon="false">
        当前有未结束任务。更换成员或版本前，请先结束任务。
      </n-alert>
      <n-form style="margin-top: 20px">
        <n-form-item label="对话名称">
          <n-input v-model:value="settingsTitle" :maxlength="100" />
        </n-form-item>
        <n-form-item label="我的背景与目标">
          <n-input
            v-model:value="settingsBackground"
            type="textarea"
            :maxlength="5000"
            :autosize="{ minRows: 5, maxRows: 10 }"
          />
        </n-form-item>
        <n-form-item v-if="isGroup" label="仅本次对话共享的知识卡">
          <n-select
            v-model:value="sharedCards"
            multiple
            filterable
            clearable
            :disabled="!!activeJob"
            :options="allCards.map((c) => ({ label: c.title, value: c.id }))"
          />
        </n-form-item>
        <n-form-item label="成员">
          <n-select
            v-model:value="settingsAgents"
            multiple
            :disabled="!!activeJob"
            :options="
              agents
                .filter((a) => !['disabled', 'archived', 'draft'].includes(a.status))
                .map((a) => ({ label: a.title, value: a.id }))
            "
          />
        </n-form-item>
      </n-form>
      <n-button type="primary" :loading="busy" @click="saveSettings">保存设置</n-button>
      <div class="section-spaced">
        <h3>当前成员</h3>
        <div v-for="a in participants" :key="a.id" class="member-setting">
          <div>
            {{ a.title }}
            <small>
              本会话 v{{ current?.data.agent_snapshots?.[a.id]?.version || a.version }} · 最新 v{{
                a.version
              }}
            </small>
            <div v-if="isAdmin" class="policy-switch">
              <n-switch
                size="small"
                :value="generalOverrides[a.id] ?? a.data.general_knowledge ?? false"
                :disabled="!!activeJob"
                @update:value="generalOverrides[a.id] = $event"
              />
              <span>允许一般知识补充</span>
            </div>
          </div>
          <n-button size="small" :disabled="!!activeJob" @click="switchVersion(a)">
            切换到此版本
          </n-button>
        </div>
      </div>
      <div class="section-spaced">
        <div class="heading-with-help">
          <h3>长期记忆</h3>
          <HelpTip label="长期记忆说明">
            提取候选后仍需到记忆页面确认，不会自动共享到其他智能体。
          </HelpTip>
        </div>
        <n-select
          v-model:value="memoryAgent"
          :options="memberOptions"
          placeholder="选择记忆所属智能体"
          style="margin-bottom: 12px"
        />
        <n-button
          :disabled="!messages.length || !!activeJob || !memoryAgent"
          @click="
            run(
              () =>
                post('/memories/extract', {
                  conversation_id: id,
                  agent_id: memoryAgent,
                  request_id: requestId(),
                }),
              '记忆候选提取任务已提交',
            )
          "
        >
          <Brain :size="14" />
          提取候选记忆
        </n-button>
      </div>
      <div class="inline-actions section-spaced">
        <n-button @click="archive">
          <Archive :size="14" />
          {{ current?.status === 'archived' ? '恢复对话' : '归档对话' }}
        </n-button>
        <n-button type="error" @click="del">
          <Trash2 :size="14" />
          删除对话
        </n-button>
      </div>
    </n-drawer-content>
  </n-drawer>
  <n-modal v-model:show="saveOpen" preset="card" title="保存为个人成果" style="width: 650px">
    <n-form>
      <n-form-item label="标题"><n-input v-model:value="saveTitle" :maxlength="100" /></n-form-item>
      <n-form-item label="类型">
        <n-select
          v-model:value="saveType"
          :options="[
            { label: '观点笔记', value: 'note' },
            { label: '问题分析', value: 'analysis' },
            { label: '讨论总结', value: 'summary' },
            { label: '行动清单', value: 'action' },
          ]"
        />
      </n-form-item>
      <n-form-item label="内容（支持 Markdown）">
        <n-input v-model:value="saveText" type="textarea" :autosize="{ minRows: 8, maxRows: 18 }" />
      </n-form-item>
    </n-form>
    <HelpTip label="使用说明">保存已有文本不调用模型，保留原会话入口和引用。</HelpTip>
    <div class="modal-footer">
      <n-button @click="saveOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="saveArtifact">保存</n-button>
    </div>
  </n-modal>
  <EvidenceDrawer v-model:show="evidenceOpen" :reference="evidence" />
</template>
<style scoped>
.selected-message-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 28px;
  font-size: 12px;
  background: var(--accent-soft);
}
.response-links {
  display: flex;
  gap: 10px;
  font-size: 10px;
  color: var(--accent);
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.response-links a:hover {
  text-decoration: underline;
}
.policy-switch {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 8px;
  font-size: 10px;
  color: var(--muted);
}
.chat-message {
  scroll-margin-top: 24px;
}
.chat-workspace {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  height: calc(100vh - 68px);
  margin: -36px -40px -56px;
}
.conversation-sidebar {
  padding: 26px 18px 20px;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface);
}
.conversation-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 22px;
}
.conversation-heading h1 {
  font-size: 18px;
  letter-spacing: 0;
}
.conversation-list {
  flex: 1;
  overflow: auto;
  margin: 18px -8px 14px;
  padding: 0 2px;
}
.conversation-item {
  padding: 13px 10px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  border-radius: 5px;
  margin-bottom: 5px;
  color: var(--text-secondary);
}
.conversation-item.active {
  background: var(--accent-soft);
  color: var(--accent);
}
.conversation-item > svg {
  margin-top: 3px;
  flex-shrink: 0;
}
.conversation-item strong {
  font-size: 12px;
  font-weight: 500;
  display: block;
  line-height: 1.6;
  word-break: break-word;
}
.conversation-item small {
  font-size: 10px;
  color: var(--muted);
  margin-top: 5px;
  display: block;
}
.chat-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.chat-main > .empty-state {
  margin: auto 40px;
  border: 0;
  background: transparent;
}
.chat-heading {
  padding: 22px 28px 18px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.chat-heading h2 {
  font-size: 17px;
}
.chat-members {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 10px;
  color: var(--muted);
  margin-top: 6px;
}
.chat-members > span + span::before {
  content: '·';
  margin-right: 8px;
}
.chat-job {
  padding: 14px 24px 0;
}
.chat-job .job-strip {
  font-size: 10px;
}
.message-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 28px max(24px, calc((100% - 880px) / 2));
  scroll-behavior: smooth;
  min-height: 100px;
}
.chat-intro {
  text-align: center;
  padding: 60px 24px;
}
.chat-intro h2 {
  font-size: 22px;
  font-family: 'Songti SC', Georgia, serif;
  margin: 12px 0;
}
.chat-intro p {
  color: var(--muted);
  font-size: 12px;
  max-width: 440px;
  margin: auto;
}
.chat-message {
  display: flex;
  gap: 14px;
  margin: 0 0 30px;
}
.message-avatar {
  height: 32px;
  width: 32px;
  flex-shrink: 0;
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid var(--border);
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-size: 12px;
  font-family: 'Songti SC', serif;
}
.message-avatar.user {
  background: var(--surface-subtle);
  color: var(--text-secondary);
  border-radius: 7px;
  font-family: inherit;
  font-size: 10px;
}
.message-body {
  flex: 1;
  min-width: 0;
}
.message-meta {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 3px 0 12px;
  font-size: 10px;
  color: var(--muted);
}
.message-meta strong {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}
.from-user .markdown-content {
  background: var(--surface-subtle);
  padding: 12px 16px;
  border-radius: 6px;
  border: 1px solid var(--border);
  display: inline-block;
  max-width: 100%;
}
.message-actions {
  display: flex;
  gap: 16px;
  align-items: center;
  margin-top: 10px;
  opacity: 0.6;
}
.chat-message:hover .message-actions,
.message-actions:focus-within {
  opacity: 1;
}
.message-actions button {
  padding: 3px 0;
  background: transparent;
  border: 0;
  color: var(--text-secondary);
  display: flex;
  gap: 5px;
  align-items: center;
  font-size: 10px;
  cursor: pointer;
}
.message-actions button:hover {
  color: var(--accent);
}
.message-references {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin: 8px 0 12px;
}
.system-message {
  justify-content: center;
  font-size: 10px;
  color: var(--muted);
  margin: 24px 0;
}
.system-message span {
  background: var(--surface-subtle);
  padding: 4px 12px;
  border-radius: 4px;
}
.chat-composer {
  padding: 16px 28px 12px;
  max-width: 980px;
  width: 100%;
  margin: auto;
}
.composer-tools {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.input-box {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}
.input-box:focus-within {
  border-color: var(--accent);
}
.input-footer {
  padding: 4px 12px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.input-footer > span {
  font-size: 9px;
  color: var(--muted);
}
.composer-note {
  font-size: 9px;
  text-align: center;
  color: var(--muted);
  margin-top: 9px;
}
.generating-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 11px;
  margin: 20px 0;
}
.pulse-dot {
  width: 6px;
  height: 6px;
  background: var(--accent);
  border-radius: 50%;
  animation: pulse 1.4s infinite;
}
.discussion-preview {
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  padding: 18px;
  border-radius: 6px;
  font-size: 12px;
}
.discussion-preview p {
  color: var(--muted);
  margin-top: 8px;
  line-height: 1.8;
}
.member-setting {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.member-setting small {
  display: block;
  color: var(--muted);
  font-size: 10px;
  margin-top: 4px;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
@media (max-width: 1200px) {
  .chat-workspace {
    grid-template-columns: 210px minmax(0, 1fr);
    margin: -28px -24px -40px;
  }
  .chat-heading {
    padding: 18px;
  }
  .chat-heading h2 {
    font-size: 14px;
  }
  .chat-composer {
    padding: 12px 18px;
  }
  .input-footer > span {
    max-width: 210px;
  }
  .message-scroll {
    padding: 24px 20px;
  }
}
</style>
