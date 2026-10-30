<script setup lang="ts">
import { computed } from 'vue';
import { post } from '../../lib/api';
import { type Entity } from '../../lib/types';
import { useAction } from '../../lib/useData';
import MarkdownText from '../MarkdownText.vue';
const props = defineProps<{ show: boolean; result: Entity | null }>(),
  emit = defineEmits(['update:show', 'changed']);
const resultOpen = computed({ get: () => props.show, set: (v) => emit('update:show', v) }),
  selectedResult = computed(() => props.result);
const { busy, run } = useAction();
async function continueLocal(r: Entity) {
  await run(async () => {
    await post('/distillations/' + r.id + '/continue-local');
    emit('changed');
  }, '任务将基于已采集资料继续');
}
</script>
<template>
  <n-drawer v-model:show="resultOpen" :width="820">
    <n-drawer-content :title="selectedResult?.title || '思想蒸馏结果'" closable>
      <template v-if="selectedResult">
        <p>联网：{{ selectedResult.data.allow_network ? '本次已开启' : '关闭' }}</p>
        <section v-if="selectedResult.data.research_failures?.length">
          <h3>采集失败清单</h3>
          <p v-for="(f, i) in selectedResult.data.research_failures" :key="i">
            {{ f.url || f.stage }}：{{ f.error }}
          </p>
          <n-button :loading="busy" @click="continueLocal(selectedResult)">
            基于已采集资料继续
          </n-button>
        </section>
        <section
          v-for="(report, index) in selectedResult.data.extensions?.reports || []"
          :key="index"
          class="section-spaced"
        >
          <h3>{{ report.dimension }}</h3>
          <MarkdownText :text="report.content" />
        </section>
        <section
          v-for="(t, index) in selectedResult.data.extensions?.tests || []"
          :key="index"
          class="surface panel-pad section-spaced"
        >
          <h3>{{ t.question }}</h3>
          <MarkdownText :text="t.answer" />
          <p>模型评价：{{ t.passed ? '通过' : '待改进' }} · {{ t.reason }}</p>
        </section>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>
