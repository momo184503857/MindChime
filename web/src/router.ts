import { createRouter, createWebHistory } from 'vue-router';
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('./layouts/WorkspaceLayout.vue'),
      meta: { area: 'front' },
      children: [
        {
          path: '',
          name: 'home',
          component: () => import('./views/Dashboard.vue'),
          meta: { title: '工作台' },
        },
        {
          path: 'library',
          name: 'library',
          component: () => import('./views/front/LibraryReader.vue'),
          meta: { title: '我的书架' },
        },
        {
          path: 'library/:id',
          name: 'source',
          component: () => import('./views/front/SourceReader.vue'),
          meta: { title: '资料阅读' },
        },
        {
          path: 'agents',
          name: 'agents',
          component: () => import('./views/front/AgentGallery.vue'),
          meta: { title: '思想智能体' },
        },
        {
          path: 'chat/:id?',
          name: 'chat',
          component: () => import('./views/Chat.vue'),
          meta: { title: '对话空间' },
        },
        {
          path: 'artifacts',
          name: 'artifacts',
          component: () => import('./views/Artifacts.vue'),
          meta: { title: '我的成果' },
        },
        {
          path: 'graph',
          name: 'graph',
          component: () => import('./views/Graph.vue'),
          meta: { title: '知识图谱' },
        },
        {
          path: 'skills',
          name: 'skills',
          component: () => import('./views/Skills.vue'),
          meta: { title: '实践 Skills' },
        },
        {
          path: 'memories',
          name: 'memories',
          component: () => import('./views/Memories.vue'),
          meta: { title: '长期记忆' },
        },
      ],
    },
    {
      path: '/admin',
      component: () => import('./layouts/AdminLayout.vue'),
      meta: { area: 'admin' },
      children: [
        {
          path: '',
          name: 'admin-home',
          component: () => import('./views/admin/Overview.vue'),
          meta: { title: '管理概览' },
        },
        {
          path: 'library',
          name: 'admin-library',
          component: () => import('./views/Library.vue'),
          meta: { title: '资料与蒸馏' },
        },
        {
          path: 'library/:id',
          name: 'admin-source',
          component: () => import('./views/SourceDetail.vue'),
          meta: { title: '资料管理' },
        },
        {
          path: 'agents',
          name: 'admin-agents',
          component: () => import('./views/Agents.vue'),
          meta: { title: '智能体管理' },
        },
        {
          path: 'skills',
          name: 'admin-skills',
          component: () => import('./views/Skills.vue'),
          props: { management: true },
          meta: { title: 'Skill 管理' },
        },
        {
          path: 'graph',
          name: 'admin-graph',
          component: () => import('./views/Graph.vue'),
          props: { management: true },
          meta: { title: '关系审核' },
        },
        {
          path: 'jobs',
          name: 'admin-jobs',
          component: () => import('./views/Jobs.vue'),
          meta: { title: '任务中心' },
        },
        {
          path: 'models',
          name: 'admin-models',
          component: () => import('./views/Settings.vue'),
          props: { section: 'models' },
          meta: { title: '模型配置' },
        },
        {
          path: 'settings',
          name: 'admin-settings',
          component: () => import('./views/Settings.vue'),
          props: { section: 'general' },
          meta: { title: '系统设置' },
        },
        {
          path: 'data',
          name: 'admin-data',
          component: () => import('./views/Settings.vue'),
          props: { section: 'data' },
          meta: { title: '数据备份与恢复' },
        },
        { path: ':pathMatch(.*)*', redirect: '/admin' },
      ],
    },
    { path: '/jobs', redirect: (to) => ({ path: '/admin/jobs', query: to.query, hash: to.hash }) },
    {
      path: '/settings',
      redirect: (to) => ({ path: '/admin/models', query: to.query, hash: to.hash }),
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior(to, from, saved) {
    return saved || (to.path === from.path ? undefined : { top: 0 });
  },
});
router.afterEach((to) => {
  document.title = `${to.meta.title || '工作台'} · ${to.meta.area === 'admin' ? '后台' : '前台'} · MindChime`;
});
