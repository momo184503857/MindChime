import { test, expect } from './fixtures';
import AxeBuilder from '@axe-core/playwright';
import path from 'node:path';

async function fixture(request: any, suffix: string) {
  const response = await request.post('/api/v1/sources/paste', {
    data: {
      title: '分区验收 ' + suffix,
      text: '第一章 原创方法\n先写下问题，再记录观察。\n\n第二章 适用边界\n只用于有限的小尝试。',
      duplicate_action: 'copy',
    },
  });
  expect(response.ok()).toBeTruthy();
  const source = await response.json();
  const card = await (
    await request.post('/api/v1/cards', {
      data: {
        title: '原创方法卡 ' + suffix,
        data: {
          type: 'method',
          content: '先写下问题，再记录观察。',
          source_ids: [source.source.id],
          references: [],
        },
      },
    })
  ).json();
  return { ...source, card };
}

test('source reading and maintenance are separate, and switching preserves location', async ({
  page,
  request,
  browserName,
}, info) => {
  const item = await fixture(request, `${info.project.name}-${Date.now()}`);
  const id = item.source.id,
    chapter = item.chapters[1]?.id || item.chapters[0].id;
  const mutations: string[] = [];
  page.on('request', (req) => {
    if (req.url().includes('/api/v1/') && !['GET', 'HEAD', 'OPTIONS'].includes(req.method()))
      mutations.push(req.method() + ' ' + req.url());
  });
  try {
    await page.goto(`/library/${id}?tab=chapters&chapter=${chapter}`);
    await expect(page.locator('.chapter-reader h2')).toHaveText(
      item.chapters.find((c: any) => c.id === chapter).title,
    );
    await expect(page.getByRole('button', { name: '蒸馏所选章节', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '编辑资料', exact: true })).toHaveCount(0);
    await expect(page.getByRole('checkbox')).toHaveCount(0);
    await expect(page.locator('.reader-chapter')).toHaveText(
      item.chapters.map((c: any) => c.title),
    );
    await page.getByRole('tab', { name: /知识卡/ }).click();
    await expect(page.getByRole('heading', { name: item.card.title, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '个人补充', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '编辑与核对', exact: true })).toHaveCount(0);
    await page.getByRole('tab', { name: '章节与原文', exact: true }).click();
    if (browserName === 'chromium')
      await page.screenshot({
        path: path.resolve('../docs/validation/areas-front-reader.png'),
        fullPage: true,
        animations: 'disabled',
      });
    await page.getByRole('link', { name: '进入后台', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/library/${id}.*chapter=${chapter}`));
    await expect(page.getByRole('button', { name: '蒸馏所选章节', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '编辑资料', exact: true })).toBeVisible();
    await expect(page.locator('.chapter-reader h2')).toHaveText(
      item.chapters.find((c: any) => c.id === chapter).title,
    );
    if (browserName === 'chromium')
      await page.screenshot({
        path: path.resolve('../docs/validation/areas-admin-source.png'),
        fullPage: true,
        animations: 'disabled',
      });
    await page.getByRole('link', { name: '返回前台', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/library/${id}.*chapter=${chapter}`));
    await page.reload();
    await expect(page.locator('.chapter-reader h2')).toHaveText(
      item.chapters.find((c: any) => c.id === chapter).title,
    );
    expect(mutations).toEqual([]);
  } finally {
    await request.delete(`/api/v1/sources/${id}?mode=derived&history=redact`);
  }
});

test('navigation, legacy links and independent sidebar state work in both themes', async ({
  page,
  browserName,
}) => {
  await page.goto('/');
  await expect(page.locator('[data-area="front"]')).toBeVisible();
  await expect(
    page.getByRole('complementary').getByRole('link', { name: '模型配置', exact: true }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: '收起导航', exact: true }).click();
  await page.getByRole('link', { name: '进入后台', exact: true }).click();
  await expect(page.getByRole('button', { name: '收起导航', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '切换到深色主题', exact: true }).click();
  for (const [url, title] of [
    ['/admin', '管理概览'],
    ['/admin/library', '资料与蒸馏'],
    ['/admin/agents', '智能体管理'],
    ['/admin/skills', 'Skill 管理'],
    ['/admin/graph', '关系审核'],
    ['/admin/jobs', '任务中心'],
    ['/admin/models', '模型配置'],
    ['/admin/settings', '系统设置'],
    ['/admin/data', '数据备份与恢复'],
  ]) {
    await page.goto(url);
    await expect(page.getByRole('heading', { name: title, exact: true }).first()).toBeVisible();
    await expect(page.locator('.nav-item.active')).toHaveCount(1);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  }
  await expect(page.getByRole('button', { name: '添加模型', exact: true })).toHaveCount(0);
  await page.goto('/admin/settings');
  await expect(page.getByRole('heading', { name: '语义检索索引', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '导出工作区', exact: true })).toHaveCount(0);
  for (const width of [1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    ).toBeTruthy();
  }
  if (browserName === 'chromium')
    await page.screenshot({
      path: path.resolve('../docs/validation/areas-admin-dark.png'),
      fullPage: true,
      animations: 'disabled',
    });
  await page.goto('/jobs?selected=compatibility-check');
  await expect(page).toHaveURL(/\/admin\/jobs\?selected=compatibility-check$/);
  await page.goto('/settings?from=old-link');
  await expect(page).toHaveURL(/\/admin\/models\?from=old-link$/);
  await page.getByRole('link', { name: '返回前台', exact: true }).click();
  await expect(page.getByRole('button', { name: '展开导航', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: '展开导航', exact: true })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('a Skill maintained in admin can be practiced twice on the front with fixed versions', async ({
  page,
  request,
}, info) => {
  const suffix = `${info.project.name}-${Date.now()}`,
    item = await fixture(request, suffix);
  const title = '前后台方法 ' + suffix;
  let skillId = '';
  try {
    await page.goto('/admin/skills');
    await page.getByRole('button', { name: '手动创建', exact: true }).click();
    const modal = page.getByRole('dialog', { name: '创建实践方法', exact: true });
    await modal.getByLabel('名称', { exact: true }).fill(title);
    await modal
      .getByLabel('适用问题与说明', { exact: true })
      .fill('把原创方法变成可以复盘的一次小尝试。');
    await modal
      .locator('.n-form-item')
      .filter({ hasText: '方法知识卡' })
      .locator('.n-select')
      .click();
    await modal.getByLabel('方法知识卡', { exact: true }).fill(item.card.title);
    await page
      .locator('.n-base-select-option__content')
      .filter({ hasText: item.card.title })
      .click();
    await modal.getByLabel('步骤标题', { exact: true }).fill('记录观察');
    await modal.getByLabel('操作说明', { exact: true }).fill('写下观察到的结果。');
    await modal.getByLabel('预期产物 / 完成标准', { exact: true }).fill('一条可核对的记录');
    await modal.getByRole('button', { name: '保存并启用', exact: true }).click();
    await expect(modal).toHaveCount(0);
    const skill = (await (await request.get('/api/v1/skills')).json()).find(
      (s: any) => s.title === title,
    );
    skillId = skill.id;
    const card = page
      .locator('.skill-card')
      .filter({ has: page.getByRole('heading', { name: title, exact: true }) });
    await card.getByRole('button', { name: '查看方法', exact: true }).click();
    await page.getByRole('button', { name: '编辑方法', exact: true }).click();
    const editor = page.getByRole('dialog', { name: '编辑实践方法', exact: true });
    await editor
      .getByLabel('适用问题与说明', { exact: true })
      .fill('编辑后即时刷新，实践仍固定各自版本。');
    await editor.getByRole('button', { name: '保存并启用', exact: true }).click();
    await expect(editor).toHaveCount(0);
    await expect(
      page.locator('.n-drawer').getByText('编辑后即时刷新，实践仍固定各自版本。', { exact: true }),
    ).toBeVisible();
    const currentSkill = await (await request.get('/api/v1/skills/' + skillId)).json();
    await page.locator('.n-drawer').getByRole('button', { name: '开始实践', exact: true }).click();
    await expect(page).toHaveURL(/\/skills\?/);
    for (let n = 1; n <= 2; n++) {
      if (n === 2) {
        await page.goto('/skills');
        await page
          .locator('.skill-card')
          .filter({ has: page.getByRole('heading', { name: title, exact: true }) })
          .getByRole('button', { name: '开始一次实践', exact: true })
          .click();
      }
      await expect(page.getByRole('button', { name: '手动创建', exact: true })).toHaveCount(0);
      await page.getByRole('button', { name: '开始记录', exact: true }).click();
      await page
        .getByLabel('记录实际完成了什么、观察到什么', { exact: true })
        .fill(`第 ${n} 次实际观察`);
      await page.getByRole('button', { name: '保存本步并继续', exact: true }).click();
      await page.locator('.n-drawer textarea').last().fill(`第 ${n} 次独立复盘`);
      await page.getByRole('button', { name: '保存复盘', exact: true }).click();
      await expect(page.getByText('复盘已保存', { exact: true })).toBeVisible();
    }
    const runs = (await (await request.get('/api/v1/runs')).json()).filter(
      (r: any) => r.data.skill_id === skillId,
    );
    expect(runs).toHaveLength(2);
    expect(new Set(runs.map((r: any) => r.id)).size).toBe(2);
    expect(runs.every((r: any) => r.data.skill_version === currentSkill.version)).toBeTruthy();
    expect(new Set(runs.map((r: any) => r.data.reflection))).toEqual(
      new Set(['第 1 次独立复盘', '第 2 次独立复盘']),
    );
  } finally {
    if (skillId) await request.delete('/api/v1/skills/' + skillId);
    await request.delete(`/api/v1/sources/${item.source.id}?mode=derived&history=redact`);
  }
});

test('graph evidence is readable on the front while editing stays in admin', async ({
  page,
  request,
}, info) => {
  const item = await fixture(request, `${info.project.name}-${Date.now()}`);
  const second = await (
    await request.post('/api/v1/cards', {
      data: {
        title: '边界卡 ' + item.source.id,
        data: { type: 'boundary', content: '只用于有限的小尝试。', source_ids: [item.source.id] },
      },
    })
  ).json();
  const relation = await (
    await request.post('/api/v1/graph/relations', {
      data: {
        title: '边界限制',
        data: {
          from_id: item.card.id,
          to_id: second.id,
          type: 'limit',
          evidence: '原文说明只用于有限的小尝试。',
        },
      },
    })
  ).json();
  try {
    await page.goto(`/graph?mode=list&source_id=${item.source.id}&selected=${relation.id}`);
    await expect(page.getByRole('heading', { name: '关系依据', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '添加关系', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '编辑', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '管理此关系', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/graph.*selected=${relation.id}`));
    await page.getByRole('button', { name: '编辑', exact: true }).click();
    const modal = page.getByRole('dialog', { name: '编辑与修复关系', exact: true });
    await modal
      .getByLabel('关系依据与前提', { exact: true })
      .fill('用户核对：仅适用于有限且可逆的尝试。');
    await modal.getByRole('button', { name: '保存并确认', exact: true }).click();
    await expect(modal).toHaveCount(0);
    await page.getByRole('link', { name: '返回前台', exact: true }).click();
    await page.getByRole('button', { name: '查看依据', exact: true }).click();
    await expect(
      page.getByText('用户核对：仅适用于有限且可逆的尝试。', { exact: true }).last(),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: '确认关系', exact: true })).toHaveCount(0);
  } finally {
    await request.delete(`/api/v1/sources/${item.source.id}?mode=derived&history=redact`);
  }
});

test('front result to Skill management preserves the selected batch without automatic generation', async ({
  page,
  request,
}) => {
  const sources = await (await request.get('/api/v1/sources')).json();
  const source = sources.find((s: any) => s.data.demo && s.title.includes('小步验证'));
  const results = await (await request.get('/api/v1/distillations?source_id=' + source.id)).json();
  const result = results.find(
    (r: any) => r.data.method_id === 'cangjie' && r.status === 'completed',
  );
  const calls: string[] = [];
  page.on('request', (req) => {
    if (
      req.method() === 'POST' &&
      /\/api\/v1\/(skills\/generate|sources\/.*\/distill|agents\/generate)/.test(req.url())
    )
      calls.push(req.url());
  });
  await page.goto(`/library/${source.id}?tab=distillations&result=${result.id}`);
  await expect(page.getByRole('dialog', { name: '蒸馏结果与证据' })).toBeVisible();
  await expect(page.getByRole('button', { name: '设为当前结果', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '从此结果生成 Skill', exact: true }).click();
  await expect(page).toHaveURL(new RegExp('/admin/skills.*distillation=' + result.id));
  const modal = page.getByRole('dialog', { name: '从方法知识卡生成 Skill', exact: true });
  await expect(modal).toBeVisible();
  expect(calls).toEqual([]);
  const detail = await (await request.get('/api/v1/distillations/' + result.id)).json();
  await expect(modal.locator('.n-base-selection-tag-wrapper')).toHaveCount(
    detail.cards.filter((c: any) => c.status !== 'disabled').length,
  );
});

test('both area home pages remain keyboard accessible and meet automated WCAG checks', async ({
  page,
}) => {
  for (const url of ['/', '/admin', '/admin/skills', '/admin/settings']) {
    await page.goto(url);
    await expect(page.locator('h1')).toBeVisible();
    await page.locator('.loading-state').waitFor({ state: 'hidden' });
    await expect(page.getByRole('link', { name: '跳到主要内容', exact: true })).toHaveAttribute(
      'href',
      '#main-content',
    );
    const result = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(result.violations).toEqual([]);
  }
});

test('Agent detail links open the exact asset across areas and start a versioned conversation', async ({
  page,
  request,
}, info) => {
  const item = await fixture(request, `${info.project.name}-${Date.now()}`);
  const agent = await (
    await request.post('/api/v1/agents', {
      data: {
        title: `分区 Agent ${info.project.name}`,
        status: 'available',
        data: {
          purpose: '对照原创方法核对一次小尝试。',
          source_ids: [item.source.id],
          card_ids: [item.card.id],
          chapter_ids: item.chapters.map((c: any) => c.id),
        },
      },
    })
  ).json();
  expect(agent.id).toBeTruthy();
  let conversationId = '';
  try {
    await page.goto('/agents?selected=' + agent.id);
    await expect(page.getByRole('heading', { name: '知识范围', exact: true })).toBeVisible();
    await expect(
      page.locator('.n-drawer').getByText(agent.data.purpose, { exact: true }),
    ).toBeVisible();
    await page.getByRole('button', { name: '维护此智能体', exact: true }).click();
    await expect(page).toHaveURL(new RegExp('/admin/agents\\?selected=' + agent.id));
    await expect(page.getByRole('button', { name: '编辑版本', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '编辑版本', exact: true }).click();
    const modal = page.getByRole('dialog', { name: '编辑智能体 · 新版本', exact: true });
    await expect(modal).toBeVisible();
    await modal.getByRole('button', { name: '取消', exact: true }).click();
    await page.goto('/agents?selected=' + agent.id);
    await page.locator('.n-drawer').getByRole('button', { name: '开始对话', exact: true }).click();
    await expect(page).toHaveURL(/\/chat\/[^/?]+$/);
    conversationId = page.url().split('/').at(-1)!;
    const conversation = await (
      await request.get('/api/v1/conversations/' + conversationId)
    ).json();
    const binding = conversation.conversation?.data || conversation.data;
    expect(binding.agent_snapshots[agent.id].version).toBe(agent.version);
    await expect(page.getByRole('button', { name: /发送/ }).last()).toBeVisible();
    const unchanged = await (await request.get('/api/v1/agents/' + agent.id)).json();
    expect(unchanged.agent.version).toBe(agent.version);
  } finally {
    if (conversationId) await request.delete('/api/v1/conversations/' + conversationId);
    await request.delete('/api/v1/agents/' + agent.id);
    await request.delete(`/api/v1/sources/${item.source.id}?mode=derived&history=redact`);
  }
});

test('front default cards stay in the active batch when another result is inspected', async ({
  page,
  request,
}) => {
  const sources = await (await request.get('/api/v1/sources')).json();
  const source = sources.find(
    (s: any) => s.data.demo && s.title.includes('小步验证') && s.data.active_distillation_id,
  );
  expect(source).toBeTruthy();
  const current = await (
    await request.get('/api/v1/distillations/' + source.data.active_distillation_id)
  ).json();
  const detail = await (await request.get('/api/v1/sources/' + source.id)).json();
  const expected = [
    ...current.cards,
    ...detail.cards.filter(
      (c: any) =>
        !c.data.distillation_id &&
        ['user', 'user_original', 'user_modified'].includes(c.data.edit_origin),
    ),
  ].map((c: any) => c.title);
  await page.goto(`/library/${source.id}?tab=cards`);
  await expect(page.locator('.knowledge-grid h3')).toHaveText(expected);
  await page.getByRole('tab', { name: '蒸馏结果', exact: true }).click();
  await page
    .locator('.result-row')
    .filter({ hasText: '仓颉' })
    .first()
    .getByRole('button', { name: '查看结果', exact: true })
    .click();
  await expect(page.getByRole('dialog', { name: '蒸馏结果与证据', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('tab', { name: /知识卡/ }).click();
  await expect(page.locator('.knowledge-grid h3')).toHaveText(expected);
  const after = await (await request.get('/api/v1/sources/' + source.id)).json();
  expect(after.source.data.active_distillation_id).toBe(source.data.active_distillation_id);
});
