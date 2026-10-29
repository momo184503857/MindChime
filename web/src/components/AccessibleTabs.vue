<script setup lang="ts">
import { ref, onMounted, onUpdated, onUnmounted, useId, nextTick } from 'vue';
import { NTabs } from 'naive-ui';
defineOptions({ inheritAttrs: false });
const root = ref<InstanceType<typeof NTabs> | null>(null);
const key = useId();
let observer: MutationObserver | undefined;
function connect() {
  const el = root.value?.$el as HTMLElement | undefined;
  if (!el) return;
  const nav = el.querySelector('.n-tabs-nav');
  nav?.setAttribute('role', 'tablist');
  nav?.setAttribute('aria-label', '内容视图');
  const tabs = Array.from(el.querySelectorAll<HTMLElement>('.n-tabs-tab'));
  tabs.forEach((tab, index) => {
    tab.id = `tabs-${key}-${index}`;
    tab.setAttribute('role', 'tab');
    const active = tab.classList.contains('n-tabs-tab--active');
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (!tab.dataset.keyboardBound) {
      tab.dataset.keyboardBound = 'true';
      tab.addEventListener('keydown', (event) => {
        const position = tabs.indexOf(tab);
        let target: number | undefined;
        if (event.key === 'ArrowRight') target = (position + 1) % tabs.length;
        if (event.key === 'ArrowLeft') target = (position - 1 + tabs.length) % tabs.length;
        if (event.key === 'Home') target = 0;
        if (event.key === 'End') target = tabs.length - 1;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          tab.click();
        }
        if (target !== undefined) {
          event.preventDefault();
          tabs[target].focus();
          tabs[target].click();
        }
      });
    }
  });
  const active = tabs.find((t) => t.getAttribute('aria-selected') === 'true');
  el.querySelectorAll<HTMLElement>('.n-tab-pane').forEach((panel) => {
    panel.setAttribute('role', 'tabpanel');
    if (active) panel.setAttribute('aria-labelledby', active.id);
  });
}
onMounted(() => {
  connect();
  const el = root.value?.$el;
  if (el instanceof HTMLElement) {
    observer = new MutationObserver(() => void nextTick(connect));
    observer.observe(el, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class'],
    });
  }
});
onUpdated(() => void nextTick(connect));
onUnmounted(() => observer?.disconnect());
</script>
<template>
  <NTabs ref="root" v-bind="$attrs"><slot /></NTabs>
</template>
