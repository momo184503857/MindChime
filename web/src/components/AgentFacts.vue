<script setup lang="ts">
import { type Entity, textOf } from '../lib/types';
import MarkdownText from './MarkdownText.vue';
defineProps<{ agent: Entity; knowledge?: any }>();
const fields = [
  { key: 'purpose', label: '用途' },
  { key: 'perspective', label: '分析视角' },
  { key: 'framework', label: '思考框架' },
  { key: 'methods', label: '常用方法' },
  { key: 'boundaries', label: '适用边界' },
];
</script>
<template>
  <section v-for="field in fields" :key="field.key" class="section-spaced">
    <h3>{{ field.label }}</h3>
    <MarkdownText :text="textOf(agent.data[field.key]) || '未填写'" />
  </section>
  <section v-if="knowledge" class="section-spaced">
    <h3>知识范围</h3>
    <p class="muted">
      {{ knowledge.cards || 0 }} 张卡片 · {{ knowledge.chapters || 0 }} 个章节 ·
      {{ knowledge.unreviewed || 0 }} 张待核对
    </p>
    <p v-for="source in knowledge.coverage || []" :key="source.source_id">{{ source.title }}</p>
  </section>
</template>
