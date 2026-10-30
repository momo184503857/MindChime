<script setup lang="ts">
import { BookOpen, Layers, ArrowUpRight } from 'lucide-vue-next';
import { type Entity, dateText } from '../lib/types';
import { assetPath, type Area } from '../lib/navigation';
import StatusBadge from './StatusBadge.vue';
defineProps<{ sources: Entity[]; area: Area }>();
</script>
<template>
  <div class="book-grid">
    <RouterLink
      v-for="(s, i) in sources"
      :key="s.id"
      :to="assetPath('source', s.id, area)"
      class="book-card surface"
    >
      <div class="book-cover" :class="`cover-${i % 4}`">
        <div class="book-spine" />
        <div class="cover-top">
          <span>{{ s.data.format?.toUpperCase() || 'DOCUMENT' }}</span>
          <Layers :size="16" v-if="s.version > 1" />
        </div>
        <h2>{{ s.title }}</h2>
        <div class="cover-bottom">
          <span>{{ s.data.author || '作者未填写' }}</span>
          <BookOpen :size="22" :stroke-width="1.2" />
        </div>
      </div>
      <div class="book-info">
        <div class="book-card-title">
          <h3 class="truncate">{{ s.title }}</h3>
          <ArrowUpRight :size="15" />
        </div>
        <div class="book-meta">
          <StatusBadge :status="s.status" />
          <span>{{ dateText(s.created_at) }}</span>
        </div>
        <n-tag
          v-if="s.data.demo || s.data.is_demo"
          size="tiny"
          :bordered="false"
          style="margin-top: 10px"
        >
          原创演示 · 非出版物
        </n-tag>
      </div>
    </RouterLink>
  </div>
</template>
<style scoped>
.book-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 24px;
}
.book-card {
  overflow: hidden;
  transition:
    border-color 0.15s,
    transform 0.15s;
}
.book-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
}
.book-cover {
  height: 224px;
  margin: 18px 18px 0;
  padding: 22px 20px 18px 26px;
  position: relative;
  display: flex;
  flex-direction: column;
  background: #e8ede5;
  color: #2b4d40;
  border-radius: 3px 7px 7px 3px;
  box-shadow: 3px 3px 0 rgba(45, 71, 52, 0.05);
}
.cover-1 {
  background: #ece6d8;
  color: #675236;
}
.cover-2 {
  background: #e3e9ec;
  color: #3d5967;
}
.cover-3 {
  background: #ebe4e1;
  color: #6c5049;
}
.book-spine {
  position: absolute;
  left: 7px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: rgba(55, 70, 50, 0.12);
}
.cover-top {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  letter-spacing: 1px;
  opacity: 0.9;
}
.book-cover h2 {
  font-family: 'Songti SC', 'Noto Serif SC', Georgia, serif;
  font-size: 23px;
  font-weight: 500;
  line-height: 1.55;
  margin-top: 25px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cover-bottom {
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 18px;
  font-size: 10px;
}
.book-info {
  padding: 18px;
}
.book-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.book-card-title h3 {
  flex: 1;
  font-size: 13px;
}
.book-card-title svg {
  color: var(--muted);
}
.book-meta {
  margin-top: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 10px;
  color: var(--muted);
}
</style>
