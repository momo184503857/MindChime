<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { Brain, Check, Trash2, Pause, Sparkles, Share2, Edit3 } from 'lucide-vue-next';
import { useRouter } from 'vue-router';
import { get, post, patch, remove } from '../lib/api';
import { useResource, useAction, useConfirm } from '../lib/useData';
import { type Entity, dateText, requestId } from '../lib/types';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import StatusBadge from '../components/StatusBadge.vue';
const router = useRouter();
const {
  data: memories,
  loading,
  error,
  reload,
} = useResource(() => get<Entity[]>('/memories'), [], 8000);
const { busy, run, message } = useAction();
const confirm = useConfirm();
const agents = ref<Entity[]>([]),
  conversations = ref<Entity[]>([]);
const filter = ref('all'),
  owner = ref<string | null>(null),
  editing = ref<Entity | null>(null),
  editOpen = ref(false),
  content = ref(''),
  ownerId = ref<string | null>(null),
  shared = ref<string[]>([]);
const extractOpen = ref(false),
  conversationId = ref<string | null>(null),
  extractAgent = ref<string | null>(null);
const candidates = computed(() => memories.value.filter((m) => m.status === 'candidate').length);
const filtered = computed(() =>
  memories.value.filter(
    (m) =>
      (filter.value === 'all' || m.status === filter.value) &&
      (!owner.value || m.data.agent_id === owner.value),
  ),
);
const extractMembers = computed(
  () => conversations.value.find((c) => c.id === conversationId.value)?.data.agent_ids || [],
);
function name(id: string) {
  return agents.value.find((a) => a.id === id)?.title || '原智能体已不可用';
}
onMounted(
  () =>
    void run(async () => {
      [agents.value, conversations.value] = await Promise.all([
        get('/agents'),
        get('/conversations'),
      ]);
    }),
);
function edit(m: Entity) {
  editing.value = m;
  content.value = m.data.content || '';
  ownerId.value = m.data.agent_id || null;
  shared.value = [...(m.data.shared_agent_ids || [])];
  editOpen.value = true;
}
async function activate(m: Entity) {
  await confirm(
    '确认这条长期记忆',
    `“${m.data.content}”将用于 ${name(m.data.agent_id)} 的后续会话。`,
    () =>
      run(async () => {
        await patch('/memories/' + m.id, { status: 'active' });
        await reload();
      }, '记忆已确认生效'),
  );
}
async function save() {
  if (!editing.value || !content.value.trim() || !ownerId.value) {
    message.warning('请填写内容并选择所属智能体');
    return;
  }
  await run(async () => {
    await patch('/memories/' + editing.value!.id, {
      data: {
        content: content.value,
        agent_id: ownerId.value,
        shared_agent_ids: shared.value.filter((a) => a !== ownerId.value),
      },
    });
    editOpen.value = false;
    await reload();
  }, '记忆内容和共享范围已保存');
}
async function disable(m: Entity) {
  await run(async () => {
    await patch('/memories/' + m.id, { status: 'disabled' });
    await reload();
  }, '记忆已停用');
}
async function del(m: Entity) {
  await confirm('删除长期记忆', '删除后不再用于后续会话，不改变已经保存的历史消息。', () =>
    run(async () => {
      await remove('/memories/' + m.id);
      await reload();
    }, '记忆已删除'),
  );
}
async function extract() {
  if (!conversationId.value || !extractAgent.value) {
    message.warning('请选择对话与记忆所属智能体');
    return;
  }
  await run(async () => {
    const job = await post('/memories/extract', {
      conversation_id: conversationId.value,
      agent_id: extractAgent.value,
      request_id: requestId(),
    });
    extractOpen.value = false;
    await router.push('/jobs?selected=' + job.id);
  }, '候选提取任务已提交');
}
</script>
<template>
  <PageHeader
    eyebrow="CONTEXT, WITH YOUR CONSENT"
    title="长期记忆"
    description="哪些背景值得带到下一次对话，由你决定。"
  >
    <n-button type="primary" @click="extractOpen = true">
      <Sparkles :size="15" />
      从对话提取候选
    </n-button>
  </PageHeader>
  <div class="memory-policy surface">
    <Brain :size="25" />
    <div>
      <h3>先提取，再确认。</h3>
      <p>候选记忆不会自动生效；确认后默认只供原智能体使用。只有你主动共享，其他智能体才能读取。</p>
    </div>
    <n-tag v-if="candidates" type="warning" :bordered="false">{{ candidates }} 条待确认</n-tag>
  </div>
  <div class="toolbar">
    <n-radio-group v-model:value="filter" size="small">
      <n-radio-button value="all">全部</n-radio-button>
      <n-radio-button value="candidate">待确认</n-radio-button>
      <n-radio-button value="active">已生效</n-radio-button>
      <n-radio-button value="disabled">已停用</n-radio-button>
    </n-radio-group>
    <n-select
      v-model:value="owner"
      :options="agents.map((a) => ({ label: a.title, value: a.id }))"
      placeholder="全部智能体"
      clearable
      style="width: 210px"
    />
  </div>
  <ResourceState
    :loading="loading"
    :error="error"
    :empty="!filtered.length"
    title="还没有这样的记忆"
    description="在对话里说明你的背景与目标，AI 可以提取候选；你始终可以修改、确认或删除。"
    @retry="reload()"
  >
    <template #icon><Brain :size="36" :stroke-width="1.3" /></template>
    <div class="memory-grid">
      <article
        v-for="m in filtered"
        :key="m.id"
        class="memory-card surface"
        :class="{ 'disabled-asset': m.status === 'disabled' }"
      >
        <div class="section-heading">
          <StatusBadge :status="m.status" />
          <span class="muted small">{{ dateText(m.created_at) }}</span>
        </div>
        <p class="memory-content">{{ m.data.content }}</p>
        <div class="memory-owner">
          <span class="avatar">{{ name(m.data.agent_id).slice(0, 1) }}</span>
          <div>
            <strong>{{ name(m.data.agent_id) }}</strong>
            <small>
              {{
                m.data.shared_agent_ids?.length
                  ? '已共享给 ' + m.data.shared_agent_ids.map(name).join('、')
                  : '仅原智能体可用'
              }}
            </small>
          </div>
        </div>
        <p class="field-hint" v-if="m.data.disabled_reason">{{ m.data.disabled_reason }}</p>
        <RouterLink
          v-if="m.data.conversation_id"
          :to="'/chat/' + m.data.conversation_id"
          class="text-link"
        >
          查看来源对话 →
        </RouterLink>
        <div class="memory-actions">
          <n-button
            v-if="m.status === 'candidate'"
            size="small"
            type="primary"
            @click="activate(m)"
          >
            <Check :size="13" />
            确认生效
          </n-button>
          <n-button v-else-if="m.status === 'active'" size="small" @click="disable(m)">
            <Pause :size="13" />
            停用
          </n-button>
          <n-button v-else size="small" @click="activate(m)">核对并重新启用</n-button>
          <n-button text size="small" @click="edit(m)">
            <Edit3 :size="12" />
            编辑与共享
          </n-button>
          <n-button text size="small" type="error" @click="del(m)" aria-label="删除记忆">
            <Trash2 :size="13" />
          </n-button>
        </div>
      </article>
    </div>
  </ResourceState>
  <n-modal v-model:show="editOpen" preset="card" title="编辑与共享记忆" style="width: 650px">
    <n-form>
      <n-form-item label="记忆内容">
        <n-input
          v-model:value="content"
          type="textarea"
          :maxlength="5000"
          :autosize="{ minRows: 5, maxRows: 10 }"
        />
      </n-form-item>
      <n-form-item label="所属智能体">
        <n-select
          v-model:value="ownerId"
          :options="agents.map((a) => ({ label: a.title, value: a.id }))"
        />
      </n-form-item>
      <n-form-item label="主动共享给其他智能体（可选）">
        <n-select
          v-model:value="shared"
          multiple
          clearable
          :options="
            agents
              .filter(
                (a) => a.id !== ownerId && !['disabled', 'draft', 'archived'].includes(a.status),
              )
              .map((a) => ({ label: a.title, value: a.id }))
          "
        />
      </n-form-item>
    </n-form>
    <n-alert type="info" :show-icon="false">
      保存编辑不会把待确认候选自动设为生效。共享仅影响这条记忆，不会开放其他资料。
    </n-alert>
    <div class="modal-footer">
      <n-button @click="editOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="save">保存</n-button>
    </div>
  </n-modal>
  <n-modal v-model:show="extractOpen" preset="card" title="提取长期记忆候选" style="width: 600px">
    <n-form>
      <n-form-item label="来源对话">
        <n-select
          v-model:value="conversationId"
          :options="conversations.map((c) => ({ label: c.title, value: c.id }))"
          @update:value="extractAgent = null"
          filterable
        />
      </n-form-item>
      <n-form-item label="记忆所属智能体">
        <n-select
          v-model:value="extractAgent"
          :options="
            agents
              .filter((a) => extractMembers.includes(a.id))
              .map((a) => ({ label: a.title, value: a.id }))
          "
        />
      </n-form-item>
    </n-form>
    <n-alert type="info" :show-icon="false">
      仅从用户明确说出的个人背景、偏好和目标提取，不根据书中内容或 AI
      回复推断你的事实。此操作会调用模型。
    </n-alert>
    <div class="modal-footer">
      <n-button @click="extractOpen = false">取消</n-button>
      <n-button type="primary" :loading="busy" @click="extract">提取候选</n-button>
    </div>
  </n-modal>
</template>
<style scoped>
.memory-policy {
  display: flex;
  gap: 18px;
  align-items: center;
  padding: 24px;
  margin-bottom: 26px;
  background: var(--accent-soft);
  border: 0;
}
.memory-policy > svg {
  color: var(--accent);
  flex-shrink: 0;
}
.memory-policy > div {
  flex: 1;
}
.memory-policy p {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 5px;
}
.memory-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 20px;
}
.memory-card {
  padding: 24px;
}
.memory-content {
  font-size: 16px;
  line-height: 1.9;
  font-family: 'Songti SC', Georgia, serif;
  margin: 22px 0;
}
.memory-owner {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
}
.memory-owner .avatar {
  height: 30px;
  width: 30px;
  font-size: 12px;
}
.memory-owner strong {
  font-size: 11px;
  font-weight: 500;
}
.memory-owner small {
  display: block;
  font-size: 10px;
  color: var(--muted);
  margin-top: 3px;
}
.memory-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  border-top: 1px solid var(--border);
  padding-top: 16px;
  margin-top: 18px;
}
.memory-actions > *:last-child {
  margin-left: auto;
}
</style>
