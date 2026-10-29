<script setup lang="ts">
import { computed } from 'vue';
import { Quote } from 'lucide-vue-next';
import type { Reference } from '../lib/types';
const props = defineProps<{ references: Reference[] }>();
const emit = defineEmits<{ (e: 'open', reference: Reference): void }>();
const groups = computed(() => {
  const result = new Map<string, { label: string; references: Reference[] }>();
  for (const reference of props.references) {
    const key = [
      reference.source_id,
      reference.source_version,
      reference.chapter_id,
      reference.chapter_version,
    ].join(':');
    const group = result.get(key) || { label: reference.label || '来源片段', references: [] };
    if (
      !group.references.some(
        (r) =>
          r.start === reference.start && r.end === reference.end && r.quote === reference.quote,
      )
    )
      group.references.push(reference);
    result.set(key, group);
  }
  return [...result.values()];
});
</script>
<template>
  <div class="reference-groups">
    <template v-for="(group, index) in groups" :key="index">
      <n-dropdown
        v-if="group.references.length > 1"
        trigger="click"
        :options="
          group.references.map((r, i) => ({
            key: i,
            label: `片段 ${i + 1} · ${(r.quote || '展开核对原文').slice(0, 36)}`,
          }))
        "
        @select="(key: number) => emit('open', group.references[key])"
      >
        <n-button size="tiny">
          <Quote :size="11" />
          {{ group.label }}（{{ group.references.length }} 处）
        </n-button>
      </n-dropdown>
      <n-button v-else size="tiny" @click="emit('open', group.references[0])">
        <Quote :size="11" />
        {{ group.label }}
      </n-button>
    </template>
  </div>
</template>
<style scoped>
.reference-groups {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  margin: 8px 0 12px;
}
.reference-groups :deep(.n-button) {
  max-width: 100%;
  height: auto;
  min-height: 24px;
}
.reference-groups :deep(.n-button__content) {
  white-space: normal;
  text-align: left;
  line-height: 1.5;
  padding: 3px 0;
  gap: 4px;
}
.reference-groups svg {
  flex-shrink: 0;
}
</style>
