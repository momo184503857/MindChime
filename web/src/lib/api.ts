const BASE = '/api/v1';
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail: any,
  ) {
    super(message);
  }
}
export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new ApiError('无法连接本地服务。请确认业务服务已经启动，再重试。', 0, null);
  }
  const json = response.headers.get('content-type')?.includes('json');
  const data =
    response.status === 204 ? null : json ? await response.json() : await response.text();
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') window.dispatchEvent(new Event('mindchime:unauthorized'));
    const detail = data?.detail ?? data;
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((v: any) => v.msg || JSON.stringify(v)).join('；')
          : detail?.message || detail?.error || JSON.stringify(detail);
    throw new ApiError(message || `请求失败（${response.status}）`, response.status, detail);
  }
  return data as T;
}
export const get = <T = any>(path: string) => api<T>(path);
export const post = <T = any>(path: string, body: unknown = {}) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body) });
export const patch = <T = any>(path: string, body: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
export const remove = <T = any>(path: string) => api<T>(path, { method: 'DELETE' });
export const upload = <T = any>(path: string, form: FormData) =>
  api<T>(path, { method: 'POST', body: form });
export async function download(path: string, fallback = 'mindchime-export.md') {
  const response = await fetch(BASE + path);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === 'string' ? data.detail : '导出失败');
  }
  const blob = await response.blob();
  const link = document.createElement('a');
  const disposition = response.headers.get('Content-Disposition') || '';
  const utf = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = disposition.match(/filename="?([^";]+)/i);
  link.download = utf ? decodeURIComponent(utf[1]) : plain ? plain[1] : fallback;
  link.href = URL.createObjectURL(blob);
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
export function events(topic: string, callback: (event: any) => void) {
  const source = new EventSource(`${BASE}/events?topic=${encodeURIComponent(topic)}`);
  const on = (e: Event) => {
    try {
      callback({
        ...JSON.parse((e as MessageEvent).data),
        event:
          e.type === 'message' ? JSON.parse((e as MessageEvent).data).event || 'message' : e.type,
      });
    } catch {
      /* heartbeat */
    }
  };
  source.onmessage = on;
  for (const name of [
    'updated',
    'created',
    'job_updated',
    'progress',
    'text_delta',
    'message',
    'completed',
    'failed',
    'cancelled',
    'state',
    'job',
    'snapshot',
  ])
    source.addEventListener(name, on);
  return () => source.close();
}
