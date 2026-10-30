import { ref, onMounted, onUnmounted, type Ref } from 'vue';
import { useMessage, useDialog } from 'naive-ui';
import { errorText } from './types';
export function useResource<T>(loader: () => Promise<T>, initial: T, poll = 0) {
  const data = ref<T>(initial) as Ref<T>;
  const loading = ref(true);
  const error = ref('');
  let alive = true;
  let revision = 0;
  let timer: ReturnType<typeof setInterval> | undefined;
  async function reload(quiet = false) {
    const requestRevision = ++revision;
    if (!quiet) loading.value = true;
    try {
      const result = await loader();
      if (alive && requestRevision === revision) {
        data.value = result;
        error.value = '';
      }
    } catch (e) {
      if (alive && requestRevision === revision) error.value = errorText(e);
    } finally {
      if (alive && requestRevision === revision) loading.value = false;
    }
  }
  onMounted(() => {
    void reload();
    if (poll) timer = setInterval(() => void reload(true), poll);
  });
  onUnmounted(() => {
    alive = false;
    if (timer) clearInterval(timer);
  });
  return { data, loading, error, reload };
}
export function useAction() {
  const busy = ref(false);
  const message = useMessage();
  async function run<T>(action: () => Promise<T>, success?: string): Promise<T | undefined> {
    if (busy.value) return;
    busy.value = true;
    try {
      const value = await action();
      if (success) message.success(success);
      return value;
    } catch (e) {
      message.error(errorText(e), { duration: 6500 });
      return undefined;
    } finally {
      busy.value = false;
    }
  }
  return { busy, run, message };
}
export function useConfirm() {
  const dialog = useDialog();
  return (title: string, content: string, action: () => Promise<unknown>) =>
    new Promise<boolean>((resolve) => {
      dialog.warning({
        title,
        content,
        positiveText: '确认',
        negativeText: '取消',
        onPositiveClick: async () => {
          await action();
          resolve(true);
        },
        onNegativeClick: () => resolve(false),
        onClose: () => resolve(false),
      });
    });
}
