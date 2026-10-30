<script setup lang="ts">
import { computed, onUnmounted, ref, useId, watch } from 'vue';
import { NPopover } from 'naive-ui';
import { CircleHelp } from 'lucide-vue-next';
const props = withDefaults(defineProps<{ label?: string; text?: string }>(), { label: '查看说明' });
const id = `help-${useId()}`;
const trigger = ref<HTMLButtonElement | null>(null),
  content = ref<HTMLElement | null>(null);
const hovered = ref(false),
  focused = ref(false),
  pinned = ref(false),
  dismissed = ref(false);
const visible = computed(
  () => !dismissed.value && (hovered.value || focused.value || pinned.value),
);
let timer: ReturnType<typeof setTimeout> | undefined;
function enter() {
  clearTimeout(timer);
  hovered.value = true;
  dismissed.value = false;
}
function leave() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    hovered.value = false;
  }, 160);
}
function close() {
  clearTimeout(timer);
  pinned.value = false;
  hovered.value = false;
  dismissed.value = true;
}
function focus() {
  focused.value = true;
  dismissed.value = false;
}
function blur() {
  focused.value = false;
  pinned.value = false;
}
function click() {
  if (pinned.value) close();
  else {
    pinned.value = true;
    dismissed.value = false;
  }
}
function outside(event: PointerEvent) {
  const target = event.target as Node;
  if (!trigger.value?.contains(target) && !content.value?.contains(target)) close();
}
function escape(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    close();
  }
}
function detach() {
  document.removeEventListener('keydown', escape, true);
  document.removeEventListener('pointerdown', outside, true);
}
watch(visible, (value) => {
  detach();
  if (value) {
    document.addEventListener('keydown', escape, true);
    document.addEventListener('pointerdown', outside, true);
  }
});
onUnmounted(() => {
  clearTimeout(timer);
  detach();
});
</script>
<template>
  <NPopover :show="visible" trigger="manual" placement="top" :show-arrow="true">
    <template #trigger>
      <button
        ref="trigger"
        type="button"
        class="help-tip"
        :aria-label="props.label"
        :aria-expanded="visible"
        :aria-describedby="visible ? id : undefined"
        @mouseenter="enter"
        @mouseleave="leave"
        @focus="focus"
        @blur="blur"
        @click.stop="click"
      >
        <CircleHelp :size="16" :stroke-width="1.7" aria-hidden="true" />
      </button>
    </template>
    <div
      :id="id"
      ref="content"
      role="tooltip"
      class="help-tip-content"
      @mouseenter="enter"
      @mouseleave="leave"
    >
      <slot>{{ text }}</slot>
    </div>
  </NPopover>
</template>
<style scoped>
.help-tip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  vertical-align: middle;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  padding: 4px;
  margin: 0 0 0 4px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--muted);
  cursor: help;
  line-height: 1;
}
.help-tip:hover,
.help-tip[aria-expanded='true'] {
  color: var(--accent);
  background: var(--accent-soft);
}
.help-tip-content {
  max-width: min(360px, calc(100vw - 48px));
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.7;
  font-size: 13px;
  font-weight: 400;
  text-align: left;
}
</style>
