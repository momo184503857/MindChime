<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  BookOpen,
  Sun,
  Moon,
  Search,
  Command,
  ArrowUpRight,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-vue-next';
import { auth, isAdmin, signOut } from '../lib/auth';
import { useAppStore } from '../stores/app';
import { get } from '../lib/api';
import { type Entity, typeLabels } from '../lib/types';
import { frontNav, adminNav, assetPath, switchArea, type Area } from '../lib/navigation';
const props = defineProps<{ area: Area }>();
const app = useAppStore();
const route = useRoute();
const router = useRouter();
const compact = ref(localStorage.getItem(`mindchime.sidebar.${props.area}`) === 'compact');
function toggleCompact() {
  compact.value = !compact.value;
  localStorage.setItem(`mindchime.sidebar.${props.area}`, compact.value ? 'compact' : 'expanded');
}
const nav = computed(() => (props.area === 'admin' ? adminNav : frontNav));
const home = computed(() => (props.area === 'admin' ? '/admin' : '/'));
const areaLabel = computed(() => (props.area === 'admin' ? '管理后台' : '知识前台'));
const opposite = computed(() => (props.area === 'admin' ? 'front' : 'admin'));
const active = (path: string) =>
  path === '/' || path === '/admin'
    ? route.path === path
    : route.path === path || route.path.startsWith(path + '/');
const searchOpen = ref(false);
const query = ref('');
const hits = ref<Entity[]>([]);
const searching = ref(false);
const searchError = ref('');
let debounce: ReturnType<typeof setTimeout> | undefined;
const online = ref<boolean | null>(null);
let healthTimer: ReturnType<typeof setInterval> | undefined;
async function health() {
  try {
    await get('/health');
    online.value = true;
  } catch {
    online.value = false;
  }
}
function search(value: string) {
  query.value = value;
  if (debounce) clearTimeout(debounce);
  debounce = setTimeout(async () => {
    if (!value.trim()) {
      hits.value = [];
      return;
    }
    searching.value = true;
    searchError.value = '';
    try {
      hits.value = await get(`/search?q=${encodeURIComponent(value)}`);
    } catch (e) {
      searchError.value = (e as Error).message;
    } finally {
      searching.value = false;
    }
  }, 250);
}
function openHit(item: Entity) {
  const id = item.kind === 'card' ? item.data.source_ids?.[0] : item.id;
  const query: Record<string, string> = {};
  if (['agent', 'skill', 'artifact', 'memory'].includes(item.kind)) query.selected = item.id;
  if (item.kind === 'card') {
    query.tab = 'cards';
    query.card = item.id;
    if (props.area === 'front' && item.data.distillation_id) {
      query.tab = 'distillations';
      query.result = item.data.distillation_id;
    }
  }
  void router.push({ path: assetPath(item.kind, id, props.area), query });
  searchOpen.value = false;
}
function keys(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    searchOpen.value = !searchOpen.value;
  }
}
onMounted(() => {
  void health();
  healthTimer = setInterval(health, 15000);
  window.addEventListener('keydown', keys);
});
onUnmounted(() => {
  clearInterval(healthTimer);
  clearTimeout(debounce);
  window.removeEventListener('keydown', keys);
});
const pageTitle = computed(() => route.meta.title || '工作台');
</script>
<template>
  <div class="app-shell" :data-area="area" :class="{ 'sidebar-compact': compact }">
    <a href="#main-content" class="skip-link">跳到主要内容</a>
    <aside class="sidebar" :aria-label="areaLabel + '导航'">
      <RouterLink :to="home" class="brand">
        <span class="brand-mark"><BookOpen :size="22" :stroke-width="1.7" /></span>
        <span v-if="!compact">
          MindChime
          <small>{{ areaLabel }}</small>
        </span>
      </RouterLink>
      <nav class="nav-main">
        <RouterLink
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          :class="['nav-item', { active: active(item.path) }]"
          :aria-label="item.label"
        >
          <component :is="item.icon" :size="18" />
          <span v-if="!compact">{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-bottom">
        <RouterLink
          v-if="isAdmin"
          :to="switchArea(route, opposite)"
          class="nav-item area-switch"
          :aria-label="area === 'admin' ? '返回前台' : '进入后台'"
        >
          <ArrowUpRight :size="18" />
          <span v-if="!compact">{{ area === 'admin' ? '返回前台' : '进入后台' }}</span>
        </RouterLink>
        <div class="instance" v-if="!compact">
          <span class="status-dot" :class="{ offline: online === false }" />
          {{ online === null ? '正在连接' : online ? '本地知识工作区' : '本地服务未连接' }}
          <span class="version">v0.2</span>
        </div>
      </div>
    </aside>
    <div class="main-shell">
      <header class="topbar">
        <div class="topbar-left">
          <button
            class="icon-button"
            :aria-label="compact ? '展开导航' : '收起导航'"
            @click="toggleCompact"
          >
            <PanelLeftOpen v-if="compact" :size="18" />
            <PanelLeftClose v-else :size="18" />
          </button>
          <nav class="topbar-breadcrumb" aria-label="面包屑">
            <RouterLink :to="home">{{ areaLabel }}</RouterLink>
            <span aria-hidden="true">/</span>
            <span class="topbar-title">{{ pageTitle }}</span>
          </nav>
          <span class="local-badge">本地版</span>
        </div>
        <div class="topbar-right">
          <span class="muted small">{{ auth.user?.username }} · {{ isAdmin ? '管理员' : '普通用户' }}</span>
          <n-button text @click="signOut().then(() => router.replace('/login'))">退出登录</n-button>
          <button class="search-trigger" @click="searchOpen = true">
            <Search :size="15" />
            <span>搜索你的知识</span>
            <kbd>
              <Command :size="11" />
              K
            </kbd>
          </button>
          <button
            class="icon-button"
            :aria-label="app.dark ? '切换到浅色主题' : '切换到深色主题'"
            @click="app.toggleTheme"
          >
            <Sun v-if="app.dark" :size="19" />
            <Moon v-else :size="19" />
          </button>
        </div>
      </header>
      <main
        id="main-content"
        class="page-container"
        :class="{ 'chat-container': route.path.startsWith('/chat') }"
        tabindex="-1"
      >
        <RouterView :key="String(route.name)" />
      </main>
    </div>
  </div>
  <n-modal
    v-model:show="searchOpen"
    preset="card"
    title="搜索个人知识"
    class="search-modal"
    style="width: 640px"
    :bordered="false"
  >
    <n-input
      :value="query"
      @update:value="search"
      placeholder="书籍、知识卡、智能体、对话或成果"
      autofocus
      clearable
    />
    <n-spin :show="searching">
      <div class="search-results">
        <n-alert v-if="searchError" type="error">{{ searchError }}</n-alert>
        <button v-for="item in hits" :key="item.id" class="search-result" @click="openHit(item)">
          <span>
            <small>{{ typeLabels[item.kind] || item.kind }}</small>
            <strong>{{ item.title }}</strong>
          </span>
          <ArrowUpRight :size="16" />
        </button>
        <p v-if="!hits.length && !searching" class="muted">
          {{ query ? '没有找到匹配内容。试试其他关键词。' : '输入关键词，仅搜索你的个人资料。' }}
        </p>
      </div>
    </n-spin>
  </n-modal>
</template>
