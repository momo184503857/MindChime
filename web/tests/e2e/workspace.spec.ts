import { test, expect } from './fixtures';
import AxeBuilder from '@axe-core/playwright';

test('all workspace pages render without runtime errors, in both desktop themes', async ({
  page,
  browserName,
}, info) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const routes = [
    ['/', '把知识，带进下一次思考。'],
    ['/library', '我的书架'],
    ['/agents', '思想智能体'],
    ['/chat', '对话空间'],
    ['/artifacts', '我的成果'],
    ['/graph', '知识图谱'],
    ['/skills', '实践 Skills'],
    ['/memories', '长期记忆'],
    ['/jobs', '任务中心'],
    ['/settings', '模型配置'],
    ['/admin', '管理概览'],
    ['/admin/library', '资料与蒸馏'],
    ['/admin/agents', '智能体管理'],
    ['/admin/skills', 'Skill 管理'],
    ['/admin/graph', '关系审核'],
    ['/admin/settings', '系统设置'],
    ['/admin/data', '数据备份与恢复'],
  ];
  for (const [path, title] of routes) {
    await page.goto(path);
    await expect(page.getByRole('heading', { name: title, exact: true }).first()).toBeVisible();
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  }
  await page.goto('/');
  await expect(page.getByRole('heading', { name: routes[0][1] })).toBeVisible();
  for (const width of [1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    ).toBeTruthy();
  }
  await page.screenshot({ path: info.outputPath(`${browserName}-light.png`), fullPage: true });
  await page.getByRole('button', { name: '切换到深色主题' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.screenshot({ path: info.outputPath(`${browserName}-dark.png`), fullPage: true });
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: '切换到浅色主题' }).click();
  expect(errors).toEqual([]);
});

test('paste a document, inspect chapters, create a user knowledge card and keep its revision', async ({
  page,
  request,
}, info) => {
  const name = `UI 验收资料 ${info.project.name} ${Date.now()}`;
  let sourceId = '';
  try {
    await page.goto('/admin/library');
    await page.getByRole('button', { name: '导入资料', exact: true }).first().click();
    await page.getByRole('tab', { name: '粘贴文本' }).click();
    await page
      .getByPlaceholder('粘贴你的资料正文，个人备注请留在资料信息中。')
      .fill(
        `# 第一章\n先写下一个需要验证的问题。再做有限的小尝试。\n\n# 第二章\n记录实际结果，并说明方法适用的前提。\n验收批次：${name}`,
      );
    await page.getByLabel('标题（必填）', { exact: true }).fill(name);
    await page.getByRole('button', { name: '导入并预检查' }).click();
    await expect(page).toHaveURL(/\/admin\/library\/[^/?]+/);
    sourceId = page.url().split('/').at(-1)!;
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await expect(page.locator('.source-text')).toContainText('验证的问题');
    await page.getByRole('tab', { name: /知识卡/ }).click();
    await page.getByRole('button', { name: '个人补充' }).click();
    await page.getByLabel('标题', { exact: true }).fill('明确的小步验证');
    await page
      .getByLabel('核心内容', { exact: true })
      .fill('先描述需要验证的判断，再记录结果。这里是用户补充。');
    await page.getByRole('button', { name: '保存版本' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: '明确的小步验证' })).toBeVisible();
    await page.getByRole('button', { name: '编辑与核对' }).click();
    await page.getByLabel('核心内容', { exact: true }).fill('用户修订：还应标注方法的适用前提。');
    await page.getByRole('button', { name: '保存版本' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(
      page.getByText('用户修订：还应标注方法的适用前提。', { exact: true }),
    ).toBeVisible();
    await expect(page.getByText('v2', { exact: true })).toBeVisible();
  } finally {
    if (sourceId) await request.delete(`/api/v1/sources/${sourceId}?mode=derived&history=redact`);
  }
});

test('action checklist saves fields and completion, independently of models', async ({
  page,
  request,
}, info) => {
  const name = `UI 行动清单 ${info.project.name} ${Date.now()}`;
  let artifactId = '';
  try {
    await page.goto('/artifacts');
    await page.getByRole('button', { name: '写一条笔记', exact: true }).first().click();
    await page.getByLabel('标题', { exact: true }).fill(name);
    await page.locator('.n-modal .n-select').click();
    await page.getByText('行动清单', { exact: true }).last().click();
    await page
      .getByPlaceholder('写下你自己的理解、前提与行动…')
      .fill('用于验证结构化清单的用户原创说明。');
    await page.getByRole('button', { name: '添加行动' }).click();
    await page.getByPlaceholder('一项具体、可观察的行动').fill('记录十五分钟尝试的实际结果');
    await page.locator('input[type="date"]').fill('2026-11-01');
    await page.getByPlaceholder('完成后记录结果，也可记录不适用的原因').fill('已记录两项观察');
    await page.getByPlaceholder('之后回看时，要检验什么？').fill('这个尝试减少了哪个未知？');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(
      page.locator('.artifact-reader').getByRole('heading', { name, exact: true }),
    ).toBeVisible();
    await page.getByRole('checkbox', { name: '完成行动 记录十五分钟尝试的实际结果' }).click();
    await expect(page.getByText('1 / 1 已完成', { exact: true })).toBeVisible();
    const items = await (await request.get('/api/v1/artifacts')).json();
    const artifact = items.find((a: any) => a.title === name);
    artifactId = artifact.id;
    expect(artifact.data.items[0]).toMatchObject({
      text: '记录十五分钟尝试的实际结果',
      due_date: '2026-11-01',
      status: 'completed',
      result: '已记录两项观察',
    });
  } finally {
    if (!artifactId) {
      const items = await (await request.get('/api/v1/artifacts')).json();
      artifactId = items.find((a: any) => a.title === name)?.id;
    }
    if (artifactId) await request.delete('/api/v1/artifacts/' + artifactId);
  }
});

test('method practice saves independent steps and reflection', async ({ page, request }, info) => {
  const suffix = `${info.project.name}-${Date.now()}`;
  let sid = '',
    skillId = '';
  try {
    const source = await (
      await request.post('/api/v1/sources/paste', {
        data: {
          title: 'UI 实践来源 ' + suffix,
          text: '记录问题，然后记录观察结果。',
          duplicate_action: 'copy',
        },
      })
    ).json();
    sid = source.source.id;
    const card = await (
      await request.post('/api/v1/cards', {
        data: {
          title: 'UI 方法 ' + suffix,
          data: {
            type: 'method',
            content: '记录问题，记录观察。',
            source_ids: [sid],
            references: [],
          },
        },
      })
    ).json();
    const skill = await (
      await request.post('/api/v1/skills', {
        data: {
          title: 'UI 实践 ' + suffix,
          data: {
            description: '手动记录实践',
            inputs: ['要验证的问题'],
            steps: [
              { title: '记录观察', instruction: '写下实际做了什么。', output: '两项真实观察' },
            ],
            card_ids: [card.id],
            source_ids: [sid],
          },
        },
      })
    ).json();
    skillId = skill.id;
    await page.goto('/skills');
    const tile = page
      .locator('.skill-card')
      .filter({ has: page.getByRole('heading', { name: skill.title, exact: true }) });
    await tile.getByRole('button', { name: '开始一次实践' }).click();
    await page.getByLabel('要验证的问题', { exact: true }).fill('这个动作是否可逆？');
    await page.getByRole('button', { name: '开始记录', exact: true }).click();
    await page
      .getByPlaceholder('也可以记录：这个方法暂时不适用，原因是…')
      .fill('先写问题，再记录了投入时间和观察结果。');
    await page.getByRole('button', { name: '保存本步并继续' }).click();
    await expect(page.locator('.n-drawer').getByText('已完成', { exact: true })).toBeVisible();
    await page.locator('.n-drawer textarea').last().fill('时间窗口合适，下次先确认前提。');
    await page.getByRole('button', { name: '保存复盘' }).click();
    await expect(page.getByText('复盘已保存', { exact: true })).toBeVisible();
  } finally {
    if (skillId) await request.delete('/api/v1/skills/' + skillId);
    if (sid) await request.delete(`/api/v1/sources/${sid}?mode=derived&history=redact`);
  }
});

test('missing source has a real error and keyboard-accessible return path', async ({ page }) => {
  await page.goto('/library/not-existing-ui-test');
  await expect(page.getByRole('alert').first()).toContainText('不存在');
  await page.getByRole('link', { name: '返回书架' }).click();
  await expect(page).toHaveURL(/\/library$/);
});

test('core pages and model form meet automated WCAG A/AA checks', async ({ page }, info) => {
  for (const path of ['/', '/library', '/settings']) {
    await page.goto(path);
    await expect(page.locator('h1')).toBeVisible();
    await page.locator('.loading-state').waitFor({ state: 'hidden' });
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    await info.attach(`axe-${path.replaceAll('/', '') || 'home'}`, {
      body: JSON.stringify(results.violations, null, 2),
      contentType: 'application/json',
    });
    expect(results.violations).toEqual([]);
  }
  await page.getByRole('button', { name: '添加模型', exact: true }).click();
  await expect(page.getByLabel('配置名称', { exact: true })).toBeVisible();
  await expect
    .poll(() =>
      page.locator('.n-modal').evaluate((el) => el.getAnimations({ subtree: true }).length),
    )
    .toBe(0);
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(results.violations).toEqual([]);
});

test('untrusted markdown never auto-fetches images or executes HTML', async ({
  page,
  request,
}, info) => {
  const title = `UI Markdown 安全 ${info.project.name} ${Date.now()}`;
  let id = '';
  const remote: string[] = [];
  page.on('request', (req) => {
    if (req.url().includes('example.invalid')) remote.push(req.url());
  });
  try {
    const response = await request.post('/api/v1/artifacts', {
      data: {
        title,
        data: {
          type: 'note',
          content:
            '![外部图片](https://example.invalid/private-image.png)\n\n<script>window.__markdownAttack=true</script>\n\n[恶意链接](javascript:alert(1))\n\n[普通链接](https://example.invalid/page)',
        },
      },
    });
    expect(response.ok()).toBeTruthy();
    id = (await response.json()).id;
    await page.goto('/artifacts');
    await page
      .getByRole('button')
      .filter({ has: page.getByRole('heading', { name: title, exact: true }) })
      .click();
    await expect(page.locator('.artifact-reader .markdown-content')).toContainText(
      '图片：外部图片',
    );
    await expect(
      page.locator('.artifact-reader img,.artifact-reader iframe,.artifact-reader script'),
    ).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).__markdownAttack)).toBeUndefined();
    expect(remote).toEqual([]);
    await expect(
      page.locator('.artifact-reader').getByRole('link', { name: '普通链接' }),
    ).toHaveAttribute('rel', 'noopener noreferrer');
  } finally {
    if (id) await request.delete('/api/v1/artifacts/' + id);
  }
});

test('historical source reports are viewable without changing the current source', async ({
  page,
  request,
}, info) => {
  const name = `历史查看 ${info.project.name} ${Date.now()}`;
  const created = await (
    await request.post('/api/v1/sources/paste', {
      data: { title: name, text: '旧版本的独立内容 ' + name, duplicate_action: 'copy' },
    })
  ).json();
  const id = created.source.id;
  try {
    await request.post('/api/v1/sources/paste', {
      data: {
        title: name + ' 新版本',
        text: '新版本内容 ' + name,
        duplicate_action: 'version',
        source_id: id,
      },
    });
    await page.goto('/library/' + id);
    await page.getByRole('tab', { name: '总览与覆盖' }).click();
    await page.getByRole('button', { name: '查看历史内容' }).last().click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(
      page
        .getByRole('dialog')
        .getByRole('heading', { name: '历史知识与处理报告（只读）', exact: true }),
    ).toBeVisible();
    await expect(
      page
        .getByRole('dialog')
        .getByRole('heading', { name: `${name} · v${created.source.version}`, exact: true }),
    ).toBeVisible();
    const current = await (await request.get('/api/v1/sources/' + id)).json();
    expect(current.source.title).toBe(name + ' 新版本');
  } finally {
    await request.delete(`/api/v1/sources/${id}?mode=derived&history=redact`);
  }
});
