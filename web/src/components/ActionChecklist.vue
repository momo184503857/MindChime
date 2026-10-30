<script setup lang="ts">
import { Plus, Trash2, CalendarDays, CheckCircle2 } from 'lucide-vue-next';
export interface ActionItem {
  text: string;
  due_date: string;
  status: string;
  result: string;
  review_question: string;
}
const props = defineProps<{ items: ActionItem[]; editing?: boolean; disabled?: boolean }>();
const emit = defineEmits<{ (e: 'update:items', items: ActionItem[]): void }>();
function update(index: number, key: keyof ActionItem, value: string) {
  emit(
    'update:items',
    props.items.map((item, i) => (i === index ? { ...item, [key]: value } : item)),
  );
}
function add() {
  emit('update:items', [
    ...props.items,
    { text: '', due_date: '', status: 'pending', result: '', review_question: '' },
  ]);
}
function remove(index: number) {
  emit(
    'update:items',
    props.items.filter((_, i) => i !== index),
  );
}
</script>
<template>
  <section class="actions-checklist">
    <div class="section-heading">
      <h3>行动清单</h3>
      <n-button v-if="editing" size="small" @click="add">
        <Plus :size="13" />
        添加行动
      </n-button>
      <span v-else class="muted small">
        {{ items.filter((i) => i.status === 'completed').length }} / {{ items.length }} 已完成
      </span>
    </div>
    <div
      v-for="(item, index) in items"
      :key="index"
      class="action-item"
      :class="{ done: item.status === 'completed' }"
    >
      <div class="action-item-main">
        <n-checkbox
          :checked="item.status === 'completed'"
          :disabled="disabled"
          @update:checked="update(index, 'status', $event ? 'completed' : 'pending')"
          :aria-label="'完成行动 ' + (item.text || index + 1)"
        />
        <n-input
          v-if="editing"
          :value="item.text"
          @update:value="update(index, 'text', $event)"
          placeholder="一项具体、可观察的行动"
        />
        <strong v-else>{{ item.text }}</strong>
        <n-button v-if="editing" size="tiny" @click="remove(index)" aria-label="删除行动项">
          <Trash2 :size="12" />
        </n-button>
      </div>
      <div v-if="editing" class="action-item-details">
        <label class="field-label">
          计划日期
          <input
            class="date-input"
            type="date"
            :value="item.due_date"
            @change="update(index, 'due_date', ($event.target as HTMLInputElement).value)"
          />
        </label>
        <n-form-item label="实际结果">
          <n-input
            :value="item.result"
            @update:value="update(index, 'result', $event)"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="完成后记录结果，也可记录不适用的原因"
          />
        </n-form-item>
        <n-form-item label="复盘问题">
          <n-input
            :value="item.review_question"
            @update:value="update(index, 'review_question', $event)"
            placeholder="之后回看时，要检验什么？"
          />
        </n-form-item>
      </div>
      <div v-else class="action-item-record">
        <span v-if="item.due_date">
          <CalendarDays :size="12" />
          {{ item.due_date }}
        </span>
        <p v-if="item.result">
          <b>结果</b>
          {{ item.result }}
        </p>
        <p v-if="item.review_question">
          <b>复盘</b>
          {{ item.review_question }}
        </p>
      </div>
    </div>
    <span v-if="!items.length" class="muted small">
      暂无行动项
      <HelpTip
        label="行动清单说明"
        :text="editing ? '添加具体行动、计划日期和复盘问题。' : '可通过编辑添加结构化行动项。'"
      />
    </span>
  </section>
</template>
<style scoped>
.actions-checklist {
  margin-top: 28px;
}
.action-item {
  padding: 16px 0;
  border-top: 1px solid var(--border);
}
.action-item-main {
  display: flex;
  gap: 10px;
  align-items: center;
}
.action-item-main strong {
  font-size: 13px;
  font-weight: 500;
  flex: 1;
  white-space: pre-wrap;
}
.action-item.done .action-item-main strong {
  text-decoration: line-through;
  color: var(--muted);
}
.action-item-details {
  padding: 14px 0 0 26px;
}
.date-input {
  display: block;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text);
  background: var(--surface);
  font: inherit;
  margin: 7px 0 18px;
  width: 190px;
}
.action-item-record {
  padding-left: 26px;
  color: var(--muted);
  font-size: 11px;
}
.action-item-record > span {
  display: flex;
  gap: 5px;
  align-items: center;
  margin-top: 8px;
}
.action-item-record p {
  margin-top: 8px;
  line-height: 1.8;
  white-space: pre-wrap;
}
.action-item-record b {
  font-weight: 500;
  color: var(--text-secondary);
  margin-right: 10px;
}
</style>
