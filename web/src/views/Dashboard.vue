<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import {
  ArrowUpRight,
  ArrowRight,
  BookOpen,
  Users,
  MessagesSquare,
  NotebookPen,
  Plus,
  Sparkles,
} from 'lucide-vue-next';
import { get, post } from '../lib/api';
import { useResource, useAction } from '../lib/useData';
import { type Entity, dateText } from '../lib/types';
import PageHeader from '../components/PageHeader.vue';
import ResourceState from '../components/ResourceState.vue';
import StatusBadge from '../components/StatusBadge.vue';
import JobStrip from '../components/JobStrip.vue';
const router = useRouter();
const { data, loading, error, reload } = useResource(() => get<any>('/dashboard'), {}, 12000);
const { busy, run } = useAction();
const counts = computed(() => data.value.counts || {});
const metrics = computed(() => [
  { label: '资料', key: 'sources', alt: 'source', icon: BookOpen, to: '/library' },
  { label: '思想智能体', key: 'agents', alt: 'agent', icon: Users, to: '/agents' },
  { label: '对话', key: 'conversations', alt: 'conversation', icon: MessagesSquare, to: '/chat' },
  { label: '成果', key: 'artifacts', alt: 'artifact', icon: NotebookPen, to: '/artifacts' },
]);
const sources = computed<Entity[]>(() => data.value.sources || data.value.recent_sources || []);
const conversations = computed<Entity[]>(
  () => data.value.conversations || data.value.recent_conversations || [],
);
const jobs = computed<Entity[]>(() => data.value.jobs || data.value.recent_jobs || []);
async function demo() {
  await run(async () => {
    await post('/demo/load');
    await reload();
    await router.push('/library');
  }, '原创演示资料已载入，蒸馏与对话仍需配置真实模型');
}
</script>
<template>
  <PageHeader
    eyebrow="YOUR KNOWLEDGE, IN CONVERSATION"
    title="把知识，带进下一次思考。"
    description="整理读过的内容，让不同的思想围绕你的真实问题展开对话。"
  >
    <n-button type="primary" @click="router.push('/library?import=1')">
      <template #icon><Plus :size="17" /></template>
      导入资料
    </n-button>
  </PageHeader>
  <ResourceState :loading="loading" :error="error" @retry="reload()">
    <div class="overview-metrics">
      <RouterLink v-for="m in metrics" :key="m.key" :to="m.to" class="metric">
        <div class="metric-label">
          <component :is="m.icon" :size="16" />
          {{ m.label }}
          <ArrowUpRight :size="14" />
        </div>
        <strong>{{ counts[m.key] ?? counts[m.alt] ?? 0 }}</strong>
        <span class="muted">进入{{ m.label }}</span>
      </RouterLink>
    </div>
    <section class="journey-panel surface">
      <div>
        <div class="eyebrow">从资料到自己的判断</div>
        <h2>每个想法，都有来处。</h2>
        <p>从一本书开始，保留来源、比较观点，再把理解转化成可以实践的方法。</p>
      </div>
      <div class="journey-steps">
        <RouterLink to="/library">
          <span>01</span>
          导入与蒸馏
          <ArrowRight :size="15" />
        </RouterLink>
        <RouterLink to="/agents">
          <span>02</span>
          创建思想智能体
          <ArrowRight :size="15" />
        </RouterLink>
        <RouterLink to="/chat">
          <span>03</span>
          让观点相遇
          <ArrowRight :size="15" />
        </RouterLink>
      </div>
    </section>
    <section
      v-if="jobs.some((j) => !['completed', 'cancelled'].includes(j.status))"
      class="section-spaced"
    >
      <div class="section-heading">
        <h2>继续处理</h2>
        <RouterLink to="/jobs" class="text-link">全部任务 →</RouterLink>
      </div>
      <JobStrip
        v-for="job in jobs
          .filter((j) => !['completed', 'cancelled'].includes(j.status))
          .slice(0, 3)"
        :key="job.id"
        :job="job"
        @changed="reload(true)"
      />
    </section>
    <div class="grid-two section-spaced">
      <section>
        <div class="section-heading">
          <h2>最近加入书架</h2>
          <RouterLink to="/library" class="text-link">查看书架 →</RouterLink>
        </div>
        <div class="surface item-list" v-if="sources.length">
          <RouterLink
            v-for="s in sources.slice(0, 4)"
            :key="s.id"
            :to="`/library/${s.id}`"
            class="list-item"
          >
            <div class="mini-book"><BookOpen :size="19" /></div>
            <div class="list-item-main">
              <div class="list-item-title">{{ s.title }}</div>
              <div class="list-item-meta">
                {{ s.data.author || '作者未填写' }} · {{ dateText(s.created_at) }}
              </div>
            </div>
            <StatusBadge :status="s.status" />
          </RouterLink>
        </div>
        <div class="small-empty surface" v-else>
          <BookOpen :size="25" />
          <h3>给一个想法安放的位置</h3>
          <p>导入自己的书籍，或载入两份原创演示资料，体验从知识到对话的过程。</p>
          <n-button :loading="busy" @click="demo">
            <template #icon><Sparkles :size="15" /></template>
            载入原创演示资料
          </n-button>
          <small>演示资料不是真实出版物，不包含预设模型回答。</small>
        </div>
      </section>
      <section>
        <div class="section-heading">
          <h2>最近的对话</h2>
          <RouterLink to="/chat" class="text-link">进入对话 →</RouterLink>
        </div>
        <div class="surface item-list" v-if="conversations.length">
          <RouterLink
            v-for="c in conversations.slice(0, 4)"
            :key="c.id"
            :to="`/chat/${c.id}`"
            class="list-item"
          >
            <div class="avatar"><MessagesSquare :size="19" /></div>
            <div class="list-item-main">
              <div class="list-item-title">{{ c.title }}</div>
              <div class="list-item-meta">
                {{ c.data.mode === 'single' ? '单聊' : '思想圆桌' }} · {{ dateText(c.updated_at) }}
              </div>
            </div>
            <ArrowUpRight :size="16" class="muted" />
          </RouterLink>
        </div>
        <div class="small-empty surface" v-else>
          <MessagesSquare :size="25" />
          <h3>一个好问题，是思考的起点</h3>
          <p>创建智能体后，带上你的背景与问题，让不同知识和判断方式相互回应。</p>
          <n-button @click="router.push('/agents')">创建第一个智能体</n-button>
        </div>
      </section>
    </div>
  </ResourceState>
</template>
<style scoped>
.overview-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 28px;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--surface);
}
.metric {
  padding: 22px 24px;
  border-right: 1px solid var(--border);
}
.metric:last-child {
  border: 0;
}
.metric-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.metric-label svg:last-child {
  margin-left: auto;
  color: var(--muted);
}
.metric strong {
  display: block;
  font-size: 32px;
  font-weight: 500;
  letter-spacing: -1px;
  margin: 8px 0 0;
}
.metric > span {
  font-size: 10px;
}
.journey-panel {
  padding: 28px 32px;
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 40px;
  background: var(--accent-soft);
  border-color: transparent;
}
.journey-panel h2 {
  font-family: 'Songti SC', Georgia, serif;
  font-size: 27px;
  font-weight: 500;
  margin: 8px 0 12px;
}
.journey-panel p {
  font-size: 12px;
  color: var(--text-secondary);
  max-width: 430px;
  line-height: 1.9;
}
.journey-steps {
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.journey-steps a {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 11px 0;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.journey-steps a:last-child {
  border-bottom: 0;
}
.journey-steps span {
  font-size: 10px;
  font-family: monospace;
  color: var(--muted);
}
.journey-steps svg {
  margin-left: auto;
  color: var(--accent);
}
.mini-book {
  width: 38px;
  height: 46px;
  display: grid;
  place-items: center;
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 2px;
  color: var(--accent);
}
.small-empty {
  min-height: 270px;
  padding: 34px;
  text-align: center;
}
.small-empty > svg {
  color: var(--accent);
  margin-bottom: 12px;
}
.small-empty p {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.8;
  max-width: 330px;
  margin: 10px auto 20px;
}
.small-empty small {
  display: block;
  font-size: 10px;
  color: var(--muted);
  margin-top: 14px;
}
@media (max-width: 1200px) {
  .metric {
    padding: 18px;
  }
  .journey-panel {
    gap: 20px;
    padding: 24px;
  }
}
</style>
