<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
  eyebrow?: string;
  descriptionIsMetadata?: boolean;
}>();
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="heading-with-help">
        <h1>{{ title }}</h1>
        <HelpTip
          v-if="description && !descriptionIsMetadata"
          :label="title + '说明'"
          :text="description"
        />
      </div>
      <p v-if="description && descriptionIsMetadata" class="page-description">{{ description }}</p>
    </div>
    <div class="page-actions"><slot /></div>
  </div>
</template>
<style scoped>
.heading-with-help {
  display: flex;
  align-items: center;
  gap: 2px;
}
</style>
