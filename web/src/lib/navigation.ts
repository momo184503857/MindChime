import type { RouteLocationNormalizedLoaded, LocationQuery, RouteLocationRaw } from 'vue-router';
import {
  BookOpen,
  LayoutDashboard,
  Users,
  MessagesSquare,
  NotebookPen,
  Network,
  ListChecks,
  Brain,
  Activity,
  SlidersHorizontal,
  Database,
  Plug,
} from 'lucide-vue-next';
export type Area = 'front' | 'admin';
export const frontNav = [
  { path: '/', label: '工作台', icon: LayoutDashboard },
  { path: '/library', label: '我的书架', icon: BookOpen },
  { path: '/agents', label: '思想智能体', icon: Users },
  { path: '/chat', label: '对话空间', icon: MessagesSquare },
  { path: '/skills', label: '实践 Skills', icon: ListChecks },
  { path: '/graph', label: '知识图谱', icon: Network },
  { path: '/artifacts', label: '我的成果', icon: NotebookPen },
  { path: '/memories', label: '长期记忆', icon: Brain },
];
export const adminNav = [
  { path: '/admin', label: '管理概览', icon: LayoutDashboard },
  { path: '/admin/library', label: '资料与蒸馏', icon: BookOpen },
  { path: '/admin/thoughts', label: '人物与思想蒸馏', icon: Brain },
  { path: '/admin/publications', label: '发布管理', icon: NotebookPen },
  { path: '/admin/agents', label: '智能体管理', icon: Users },
  { path: '/admin/skills', label: 'Skill 管理', icon: ListChecks },
  { path: '/admin/graph', label: '关系审核', icon: Network },
  { path: '/admin/jobs', label: '任务中心', icon: Activity },
  { path: '/admin/models', label: '模型配置', icon: Plug },
  { path: '/admin/settings', label: '系统设置', icon: SlidersHorizontal },
  { path: '/admin/data', label: '数据备份与恢复', icon: Database },
];
export function assetPath(kind: string, id: string | undefined, area: Area): string {
  const prefix = area === 'admin' ? '/admin' : '';
  const paths: Record<string, string> = {
    source: `${prefix}/library${id ? '/' + encodeURIComponent(id) : ''}`,
    card: `${prefix}/library${id ? '/' + encodeURIComponent(id) : ''}`,
    agent: `${prefix}/agents`,
    skill: `${prefix}/skills`,
    relation: `${prefix}/graph`,
    conversation: `/chat${id ? '/' + encodeURIComponent(id) : ''}`,
    artifact: '/artifacts',
    memory: '/memories',
  };
  return paths[kind] || (area === 'admin' ? '/admin' : '/');
}
export const jobPath = (id: string) => ({ path: '/admin/jobs', query: { selected: id } });
export function switchArea(route: RouteLocationNormalizedLoaded, area: Area): RouteLocationRaw {
  const query: LocationQuery = { ...route.query };
  // Commands belong to their originating page; switching only opens a view.
  for (const key of ['import', 'create', 'edit', 'start', 'source', 'distillation'])
    delete query[key];
  const path = route.path.replace(/^\/admin(?=\/|$)/, '') || '/';
  if (/^\/(library|agents|skills|graph)(\/|$)/.test(path))
    return { path: area === 'admin' ? '/admin' + path : path, query, hash: route.hash };
  return area === 'admin' ? '/admin' : '/';
}
