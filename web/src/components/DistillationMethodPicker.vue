<script setup lang="ts">
import type { DistillationMethod } from '../lib/types';
defineProps<{ methods: DistillationMethod[]; modelValue: string }>();
defineEmits(['update:modelValue']);
</script>
<template>
  <fieldset class="method-picker">
    <legend>蒸馏方法</legend>
    <label
      v-for="method in methods"
      :key="method.id"
      class="method-option"
      :class="{ chosen: modelValue === method.id }"
    >
      <input
        type="radio"
        name="distillation-method"
        :value="method.id"
        :checked="modelValue === method.id"
        @change="$emit('update:modelValue', method.id)"
      />
      <span>
        <strong>{{ method.name }}</strong>
        <small>{{ method.description }}</small>
        <small>调用量：{{ method.cost }} · v{{ method.version }}</small>
      </span>
    </label>
  </fieldset>
</template>
<style scoped>
.method-picker {
  border: 0;
  padding: 0;
  margin: 0 0 24px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
legend {
  font-weight: 600;
  padding: 0 0 12px;
}
.method-option {
  display: flex;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--border);
  cursor: pointer;
  border-radius: 8px;
}
.method-option.chosen {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.method-option input {
  margin-top: 4px;
  flex-shrink: 0;
  accent-color: var(--accent);
}
.method-option small {
  display: block;
  margin-top: 8px;
  color: var(--muted);
  line-height: 1.6;
}
.method-option:focus-within {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
