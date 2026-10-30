import { reactive, computed } from 'vue';
import { get, post } from './api';
export interface LocalUser {
  id: string;
  username: string;
  role: 'admin' | 'user';
}
export const auth = reactive<{ user: LocalUser | null; loaded: boolean }>({
  user: null,
  loaded: false,
});
export const isAdmin = computed(() => auth.user?.role === 'admin');
let pending: Promise<void> | null = null;
export async function loadAuth() {
  if (auth.loaded) return;
  if (!pending)
    pending = (async () => {
      try {
        auth.user = await get<LocalUser>('/auth/me');
      } catch {
        auth.user = null;
      } finally {
        auth.loaded = true;
        pending = null;
      }
    })();
  await pending;
}
export async function signIn(username: string, password: string) {
  auth.user = await post<LocalUser>('/auth/login', { username, password });
  auth.loaded = true;
}
export async function signOut() {
  await post('/auth/logout');
  auth.user = null;
  auth.loaded = true;
}
