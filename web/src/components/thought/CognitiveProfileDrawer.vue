<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { patch } from '../../lib/api';
import { type Entity } from '../../lib/types';
import { useAction } from '../../lib/useData';
import MarkdownText from '../MarkdownText.vue';
import EvidenceDrawer from '../EvidenceDrawer.vue';
const props = defineProps<{ show: boolean; profile: Entity | null }>(),
  emit = defineEmits(['update:show', 'changed']);
const detailOpen = computed({ get: () => props.show, set: (v) => emit('update:show', v) }),
  detail = ref<Entity | null>(null),
  evidenceOpen = ref(false),
  evidence = ref<any>(null);
const router = useRouter(),
  { busy, run } = useAction();
const labels: Record<string, string> = {
  mental_models: '心智模型',
  decision_heuristics: '决策规则',
  values: '价值观',
  analysis_protocol: '分析步骤',
  expression_style: '表达特征',
  anti_patterns: '反模式',
  contradictions: '思想矛盾',
  limits: '适用边界',
};
watch(
  () => props.profile,
  (p) => {
    detail.value = p ? JSON.parse(JSON.stringify(p)) : null;
  },
  { immediate: true },
);
async function saveReview(enable = false) {
  if (!detail.value) return;
  await run(
    async () => {
      detail.value = await patch('/cognitive-profiles/' + detail.value!.id, {
        rules: detail.value!.data.rules,
        ...(enable ? { status: 'active' } : {}),
      });
      emit('changed');
    },
    enable ? '思想版本已启用，可在发布管理中检查并发布' : '人工审核已保存',
  );
}
</script>
<template>
  <n-drawer v-model:show="detailOpen" :width="820">
    <n-drawer-content :title="detail?.title || '思想画像'" closable>
      <template v-if="detail">
        <p class="muted">{{ detail.data.identity_notice }} · v{{ detail.version }}</p>
        <p v-if="detail.data.missing_dimensions?.length" class="muted">
          资料不足：{{ detail.data.missing_dimensions.join('、') }}
        </p>
        <article
          v-for="rule in detail.data.rules"
          :key="rule.id"
          class="surface panel-pad section-spaced"
        >
          <div class="section-heading">
            <h3>{{ rule.name }}</h3>
            <n-tag>{{ labels[rule.category] || rule.category }}</n-tag>
          </div>
          <p>
            <strong>触发：</strong>
            {{ rule.trigger }}
          </p>
          <MarkdownText :text="rule.behavior" />
          <p class="muted">边界：{{ rule.limitations }}</p>
          <p class="muted small">
            归因：{{ rule.attribution }} · 结构检查：{{
              rule.structural_valid ? '引用可定位' : '证据不足'
            }}
          </p>
          <p v-if="rule.model_assessment" class="muted small">
            模型评价：{{ rule.model_assessment.reason }}（不代表人工确认）
          </p>
          <div class="inline-actions">
            <n-button
              v-for="(ref, index) in rule.references"
              :key="index"
              size="small"
              @click="
                evidence = ref;
                evidenceOpen = true;
              "
            >
              核对原文 {{ Number(index) + 1 }}
            </n-button>
          </div>
          <n-form-item label="人工审核">
            <n-select
              v-model:value="rule.review_status"
              :options="[
                { label: '待人工审核', value: 'pending_review' },
                { label: '候选，暂不使用', value: 'candidate' },
                { label: '已核对确认', value: 'verified', disabled: !rule.structural_valid },
                { label: '不采用', value: 'rejected' },
              ]"
            />
          </n-form-item>
          <n-input v-model:value="rule.review_note" placeholder="审核说明（可选）" />
        </article>
        <div class="inline-actions section-spaced">
          <n-button :loading="busy" @click="saveReview()">保存审核</n-button>
          <n-button type="primary" :loading="busy" @click="saveReview(true)">启用思想版本</n-button>
          <n-button @click="router.push('/admin/publications')">检查并发布</n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
  <EvidenceDrawer v-model:show="evidenceOpen" :reference="evidence" />
</template>
