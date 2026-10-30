<script setup lang="ts">
import { isAdmin } from '../../lib/auth';
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { get } from '../../lib/api';
import { useResource } from '../../lib/useData';
import type { Entity } from '../../lib/types';
import PageHeader from '../../components/PageHeader.vue';
import ResourceState from '../../components/ResourceState.vue';
import LibraryShelf from '../../components/LibraryShelf.vue';
const router = useRouter();
const {
  data: sources,
  loading,
  error,
  reload,
} = useResource(() => get<Entity[]>('/sources'), [], 10000);
const query = ref('');
const filtered = computed(() =>
  sources.value.filter((s) =>
    `${s.title} ${s.data.author || ''}`.toLowerCase().includes(query.value.toLowerCase()),
  ),
);
</script>
<template>
  <PageHeader title="我的书架" description="阅读原文、查阅知识与证据，把理解带入下一次思考。">
    <n-button v-if="isAdmin" @click="router.push('/admin/library')">管理资料</n-button>
  </PageHeader>
  <div class="toolbar">
    <n-input v-model:value="query" class="search-field" placeholder="搜索标题或作者" clearable />
    <span class="muted small">共 {{ sources.length }} 份资料</span>
  </div>
  <ResourceState
    :loading="loading"
    :error="error"
    :empty="!filtered.length"
    title="从一份值得阅读的资料开始"
    :description="isAdmin ? '在后台导入书籍并审核发布，然后回到这里阅读。' : '暂时没有已发布资料，请等待管理员发布。'"
    @retry="reload()"
  >
    <template #action>
      <n-button v-if="isAdmin" @click="router.push('/admin/library?import=1')">去后台导入资料</n-button>
    </template>
    <LibraryShelf :sources="filtered" area="front" />
  </ResourceState>
</template>
