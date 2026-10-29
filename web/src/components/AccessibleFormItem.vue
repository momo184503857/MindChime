<script setup lang="ts">
import { onMounted, onUpdated, ref, useId } from 'vue';
import { NFormItem } from 'naive-ui';
defineOptions({ inheritAttrs: false });
const labelId = `field-label-${useId()}`;
const root = ref<InstanceType<typeof NFormItem> | null>(null);
function connectLabel() {
  const el = root.value?.$el as HTMLElement | undefined;
  const label = el?.querySelector('label');
  if (!el || !label) return;
  label.id = labelId;
  el.querySelectorAll<HTMLElement>('.n-input-number').forEach((number) => {
    number.querySelectorAll('button').forEach((button, index) => {
      button.setAttribute(
        'aria-label',
        `${index === 0 ? '减少' : '增加'} ${label.textContent || '数值'}`,
      );
    });
  });
  const fields = el.querySelectorAll<HTMLInputElement>(
    'input:not([type="hidden"]),textarea,[role="combobox"],[role="switch"]',
  );
  fields.forEach((field, index) => {
    if (!field.hasAttribute('aria-label')) field.setAttribute('aria-labelledby', labelId);
    if (index === 0 && ['INPUT', 'TEXTAREA'].includes(field.tagName)) {
      field.id ||= `${labelId}-input`;
      label.htmlFor = field.id;
    }
  });
}
onMounted(connectLabel);
onUpdated(connectLabel);
</script>
<template>
  <NFormItem ref="root" v-bind="$attrs">
    <template #label v-if="$slots.label"><slot name="label" /></template>
    <slot />
    <template #feedback v-if="$slots.feedback"><slot name="feedback" /></template>
  </NFormItem>
</template>
