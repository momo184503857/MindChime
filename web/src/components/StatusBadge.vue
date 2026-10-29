<script setup lang="ts">
import { computed } from 'vue';
import { stateLabels } from '../lib/types';
const props = defineProps<{ status: string }>();
const type = computed(() =>
  [
    'active',
    'ready',
    'completed',
    'available',
    'reviewed',
    'verified',
    'confirmed',
    'parsed',
  ].includes(props.status)
    ? 'success'
    : ['failed', 'deleted'].includes(props.status)
      ? 'error'
      : [
            'candidate',
            'draft',
            'paused',
            'interrupted',
            'incomplete',
            'needs_ocr',
            'partial',
            'partial_completed',
            'waiting',
            'waiting_error',
            'pending',
          ].includes(props.status)
        ? 'warning'
        : 'default',
);
</script>
<template>
  <n-tag :type="type" size="small" :bordered="false" round>
    {{ stateLabels[status] || status }}
  </n-tag>
</template>
