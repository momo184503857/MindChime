<script setup lang="ts">
import { computed } from 'vue';
import {
  NConfigProvider,
  NMessageProvider,
  NDialogProvider,
  darkTheme,
  zhCN,
  dateZhCN,
} from 'naive-ui';
import { useAppStore } from './stores/app';
import Shell from './components/Shell.vue';
const app = useAppStore();
const theme = computed(() => ({
  common: {
    primaryColor: app.dark ? '#79c7b5' : '#276c60',
    primaryColorHover: app.dark ? '#99dccd' : '#358273',
    primaryColorPressed: '#205a50',
    primaryColorSuppl: '#276c60',
    successColor: app.dark ? '#79c7a2' : '#216648',
    warningColor: app.dark ? '#e3b95f' : '#805611',
    errorColor: app.dark ? '#ed9d92' : '#ac3c32',
    infoColor: app.dark ? '#92bed8' : '#2d647b',
    textColor3: app.dark ? '#a3b3aa' : '#586c60',
    placeholderColor: app.dark ? '#a3b3aa' : '#61736a',
    borderRadius: '6px',
    fontFamily:
      'Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    fontSize: '14px',
  },
  Button: { fontWeight: '500' },
}));
</script>
<template>
  <NConfigProvider
    :theme="app.dark ? darkTheme : null"
    :theme-overrides="theme"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <NMessageProvider>
      <NDialogProvider><Shell /></NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
