<script setup lang="ts">
import type { DistillationMethod } from '../lib/types';
defineProps<{ methods: DistillationMethod[]; modelValue: string }>();
defineEmits(['update:modelValue']);
</script>
<template>
  <n-form-item label="蒸馏方法">
    <fieldset class="method-picker" aria-label="蒸馏方法">
      <div
        v-for="method in methods"
        :key="method.id"
        class="method-option"
        :class="{ chosen: modelValue === method.id }"
      >
        <label class="method-choice">
          <input
            type="radio"
            name="distillation-method"
            :aria-label="method.name"
            :value="method.id"
            :checked="modelValue === method.id"
            @change="$emit('update:modelValue', method.id)"
          />
          <strong>{{ method.name }}</strong>
        </label>
        <HelpTip :label="method.name + '方法说明'">
          {{ method.description }}
          <br />
          调用量：{{ method.cost }} · v{{ method.version }}
        </HelpTip>
      </div>
    </fieldset>
  </n-form-item>
</template>
<style scoped>
.method-picker {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
  width: 100%;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
  gap: 12px;
}
.method-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.method-choice {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  cursor: pointer;
  min-width: 0;
}
.method-option.chosen {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.method-option input {
  flex-shrink: 0;
  accent-color: var(--accent);
}
.method-option:focus-within {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
