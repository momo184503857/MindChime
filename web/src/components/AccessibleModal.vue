<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, watch, useAttrs } from 'vue';
import { NModal } from 'naive-ui';
defineOptions({ inheritAttrs: false });
const attrs = useAttrs();
function connect() {
  document.querySelectorAll<HTMLElement>('.n-modal[role="dialog"]').forEach((modal) => {
    const title = modal.querySelector('.n-card-header__main')?.textContent?.trim();
    if (title && !modal.hasAttribute('aria-label') && !modal.hasAttribute('aria-labelledby'))
      modal.setAttribute('aria-label', title);
  });
  document.querySelectorAll('.n-modal [role="heading"]').forEach((heading) => {
    if (!heading.hasAttribute('aria-level')) heading.setAttribute('aria-level', '2');
  });
}
let observer: MutationObserver | undefined;
onMounted(() => {
  observer = new MutationObserver(connect);
  observer.observe(document.body, { childList: true, subtree: true });
  connect();
});
watch(
  () => attrs.show,
  () => void nextTick(connect),
);
onUnmounted(() => observer?.disconnect());
</script>
<template>
  <NModal v-bind="$attrs" @after-enter="connect">
    <template v-for="(_, name) in $slots" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps || {}" />
    </template>
  </NModal>
</template>
