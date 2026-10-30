import { createApp } from 'vue';
import { createPinia } from 'pinia';
import {
  create,
  NButton,
  NInput,
  NInputNumber,
  NSelect,
  NTag,
  NCheckbox,
  NCheckboxGroup,
  NRadio,
  NRadioGroup,
  NRadioButton,
  NSwitch,
  NModal,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NSpace,
  NTabs,
  NTabPane,
  NAlert,
  NSpin,
  NSkeleton,
  NEmpty,
  NTooltip,
  NDivider,
  NProgress,
  NCollapse,
  NCollapseItem,
  NDatePicker,
  NUpload,
  NUploadDragger,
  NText,
  NDropdown,
  NBreadcrumb,
  NBreadcrumbItem,
  NDataTable,
  NPopconfirm,
  NStatistic,
} from 'naive-ui';
import App from './App.vue';
import AccessibleFormItem from './components/AccessibleFormItem.vue';
import AccessibleTabs from './components/AccessibleTabs.vue';
import AccessibleModal from './components/AccessibleModal.vue';
import HelpTip from './components/HelpTip.vue';
import { router } from './router';
import './style.css';
const naive = create({
  components: [
    NButton,
    NInput,
    NInputNumber,
    NSelect,
    NTag,
    NCheckbox,
    NCheckboxGroup,
    NRadio,
    NRadioGroup,
    NRadioButton,
    NSwitch,
    NModal,
    NDrawer,
    NDrawerContent,
    NForm,
    NFormItem,
    NSpace,
    NTabs,
    NTabPane,
    NAlert,
    NSpin,
    NSkeleton,
    NEmpty,
    NTooltip,
    NDivider,
    NProgress,
    NCollapse,
    NCollapseItem,
    NDatePicker,
    NUpload,
    NUploadDragger,
    NText,
    NDropdown,
    NBreadcrumb,
    NBreadcrumbItem,
    NDataTable,
    NPopconfirm,
    NStatistic,
  ],
});
createApp(App)
  .use(createPinia())
  .use(router)
  .use(naive)
  .component('NFormItem', AccessibleFormItem)
  .component('NTabs', AccessibleTabs)
  .component('NModal', AccessibleModal)
  .component('HelpTip', HelpTip)
  .mount('#app');
