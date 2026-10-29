export interface Entity {
  id: string;
  kind: string;
  title: string;
  status: string;
  version: number;
  parent_id?: string | null;
  data: Record<string, any>;
  created_at: string;
  updated_at: string;
}
export interface Reference {
  source_id: string;
  source_version?: number;
  chapter_id?: string;
  chapter_version?: number;
  start?: number;
  end?: number;
  quote?: string;
  label?: string;
}
export interface Profile {
  id: string;
  name: string;
  protocol: string;
  base_url: string;
  model: string;
  enabled: boolean;
  version: number;
  configured?: boolean;
  has_key?: boolean;
  capabilities: Record<string, any>;
  parameters: Record<string, any>;
  test_status?: string;
  last_test_at?: string;
  last_test_error?: string;
  credential_source?: string;
  configuration_notice?: string;
}
export const stateLabels: Record<string, string> = {
  active: '可用',
  ready: '可用',
  available: '可用',
  draft: '草稿',
  parsed: '已解析',
  needs_ocr: '待识别',
  pending: '待核对',
  verified: '用户已核对',
  queued: '排队中',
  running: '处理中',
  processing: '处理中',
  completed: '已完成',
  partial: '部分完成',
  partial_completed: '部分完成',
  failed: '失败',
  cancelled: '已取消',
  cancelling: '正在停止',
  paused: '已暂停',
  pausing: '请求暂停中',
  pause_requested: '请求暂停中',
  waiting: '等待处理',
  waiting_error: '等待处理异常',
  interrupted: '已中断',
  disabled: '来源失效',
  archived: '已归档',
  deleted: '已删除',
  candidate: '待确认',
  confirmed: '已确认',
  reviewed: '已核对',
  unreviewed: '待核对',
  questionable: '存在疑问',
  incomplete: '知识不完整',
};
export const typeLabels: Record<string, string> = {
  source: '资料',
  chapter: '章节',
  card: '知识卡',
  agent: '智能体',
  conversation: '对话',
  artifact: '成果',
  skill: '实践 Skill',
  memory: '记忆',
  relation: '关系',
  concept: '概念',
  viewpoint: '观点',
  claim: '观点',
  example: '例子',
  fact: '事实',
  method: '方法',
  boundary: '边界',
  note: '观点笔记',
  analysis: '问题分析',
  summary: '讨论总结',
  action: '行动清单',
  support: '支持',
  limit: '限制',
  refute: '反驳',
  apply: '应用',
  similar: '相似',
};
export const liveJobStates = [
  'queued',
  'running',
  'processing',
  'pausing',
  'pause_requested',
  'cancelling',
];
export function dateText(value?: string) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value));
}
export function textOf(value: any): string {
  if (value == null) return '';
  return typeof value === 'string'
    ? value
    : Array.isArray(value)
      ? value.map(textOf).join('\n')
      : JSON.stringify(value, null, 2);
}
export function requestId() {
  return crypto.randomUUID();
}
export function errorText(error: unknown) {
  return error instanceof Error ? error.message : '操作失败，请重试';
}

export const jobLabels: Record<string, string> = {
  distill: '内容蒸馏',
  ocr: '扫描页识别',
  agent_generate: '生成智能体',
  chat: '对话回复',
  discussion: '思想圆桌',
  summary: '讨论总结',
  artifact_generate: '整理成果',
  skill_generate: '生成实践方法',
  skill_step: '实践引导',
  memory_extract: '记忆候选提取',
  graph_generate: '知识关系提取',
  index_rebuild: '重建检索索引',
};

export function locationLabel(locator: any): string {
  if (!locator) return '来源文本分段';
  if (typeof locator === 'string') return locator;
  if (locator.type === 'pdf_page') return `文档第 ${locator.page} 页`;
  if (locator.type === 'text_offsets')
    return `正文字符 ${Number(locator.start || 0) + 1}–${locator.end || ''}`;
  if (locator.type === 'docx_paragraph')
    return `文档第 ${locator.paragraph || locator.index || ''} 段`;
  if (locator.type === 'epub_section' || locator.type === 'epub_spine') return 'EPUB 原始阅读顺序';
  if (locator.page) return `文档第 ${locator.page} 页`;
  if (locator.start != null && locator.end != null)
    return `正文字符 ${Number(locator.start) + 1}–${locator.end}`;
  return '原始文档分段';
}

export interface DistillationMethod {
  id: string;
  name: string;
  description: string;
  version: string;
  cost: string;
  upstream: string;
  upstream_version: string;
  license: string;
  adaptation: string;
  stages: { id: string; title: string; instruction: string; mode: string }[];
}
export interface DistillationInput {
  method_id: string;
  chapter_ids: string[];
  prompt: string;
  model_profile_id?: string;
  request_id: string;
}
