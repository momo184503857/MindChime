import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
export const useAppStore = defineStore('app', () => {
  const theme = ref(localStorage.getItem('mindchime.theme') || 'light');
  const dark = computed(() => theme.value === 'dark');
  function toggleTheme() {
    theme.value = dark.value ? 'light' : 'dark';
    localStorage.setItem('mindchime.theme', theme.value);
    document.documentElement.dataset.theme = theme.value;
  }
  document.documentElement.dataset.theme = theme.value;
  return { theme, dark, toggleTheme };
});
