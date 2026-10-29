import { createRouter, createWebHistory } from 'vue-router';
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('./views/Dashboard.vue'), meta: { title: '工作台' } },
    {
      path: '/library',
      component: () => import('./views/Library.vue'),
      meta: { title: '我的书架' },
    },
    {
      path: '/library/:id',
      component: () => import('./views/SourceDetail.vue'),
      meta: { title: '资料详情' },
    },
    {
      path: '/agents',
      component: () => import('./views/Agents.vue'),
      meta: { title: '思想智能体' },
    },
    {
      path: '/chat/:id?',
      component: () => import('./views/Chat.vue'),
      meta: { title: '对话空间' },
    },
    {
      path: '/artifacts',
      component: () => import('./views/Artifacts.vue'),
      meta: { title: '我的成果' },
    },
    { path: '/graph', component: () => import('./views/Graph.vue'), meta: { title: '知识图谱' } },
    {
      path: '/skills',
      component: () => import('./views/Skills.vue'),
      meta: { title: '实践 Skills' },
    },
    {
      path: '/memories',
      component: () => import('./views/Memories.vue'),
      meta: { title: '长期记忆' },
    },
    { path: '/jobs', component: () => import('./views/Jobs.vue'), meta: { title: '任务中心' } },
    { path: '/settings', component: () => import('./views/Settings.vue'), meta: { title: '设置' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});
router.afterEach((to) => {
  document.title = `${to.meta.title || '工作台'} · MindChime`;
});
