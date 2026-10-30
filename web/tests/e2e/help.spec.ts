import { test, expect } from './fixtures';
import AxeBuilder from '@axe-core/playwright';
import path from 'node:path';

const assignmentHelp =
  '除向量检索外，留空的用途会沿用默认模型。图片识别需选择支持图片输入的模型；向量检索必须配置对应能力。';

test('model assignment explanations appear only on help hover, remain hoverable and preserve settings', async ({
  page,
  request,
  browserName,
}) => {
  const before = await (await request.get('/api/v1/settings')).json();
  const mutations: string[] = [];
  page.on('request', (req) => {
    if (req.url().includes('/api/v1/') && req.method() !== 'GET') mutations.push(req.method());
  });
  await page.goto('/admin/models');
  const heading = page.getByRole('heading', { name: '默认模型与任务分配', exact: true });
  const help = page.getByRole('button', { name: '默认模型与任务分配说明', exact: true });
  await expect(heading).toBeVisible();
  await expect(page.getByText(assignmentHelp, { exact: true })).not.toBeVisible();
  await expect(help).toHaveAttribute('aria-expanded', 'false');
  await heading.scrollIntoViewIfNeeded();
  if (browserName === 'chromium')
    await page.screenshot({
      path: path.resolve('../docs/validation/help-models-compact.png'),
      animations: 'disabled',
    });
  await help.hover();
  const popup = page.locator('.help-tip-content').filter({ hasText: assignmentHelp });
  await expect(popup).toBeVisible();
  await popup.hover();
  await page.waitForTimeout(220); // Cross the pointer-leave grace period.
  await expect(popup).toBeVisible();
  if (browserName === 'chromium')
    await page.screenshot({
      path: path.resolve('../docs/validation/help-models-hover.png'),
      animations: 'disabled',
    });
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  await page.mouse.move(0, 0);
  await expect(popup).not.toBeVisible();
  await page.getByRole('button', { name: '切换到深色主题' }).click();
  await help.hover();
  await expect(popup).toBeVisible();
  if (browserName === 'chromium')
    await page.screenshot({
      path: path.resolve('../docs/validation/help-models-dark.png'),
      animations: 'disabled',
    });
  expect(mutations).toEqual([]);
  expect(await (await request.get('/api/v1/settings')).json()).toEqual(before);
});

test('help supports focus, click, outside dismissal and Escape without closing its modal', async ({
  page,
}) => {
  await page.goto('/admin/models');
  const help = page.getByRole('button', { name: '默认模型与任务分配说明', exact: true });
  await help.focus();
  const popup = page.locator('.help-tip-content').filter({ hasText: assignmentHelp });
  await expect(popup).toBeVisible();
  const describedBy = await help.getAttribute('aria-describedby');
  expect(describedBy).toBeTruthy();
  await expect(page.locator(`[id="${describedBy}"]`)).toHaveAttribute('role', 'tooltip');
  await page.keyboard.press('Escape');
  await expect(popup).not.toBeVisible();
  await expect(help).toBeFocused();
  await help.click();
  await expect(popup).toBeVisible();
  await help.click();
  await expect(popup).not.toBeVisible();
  await help.click();
  await expect(popup).toBeVisible();
  await page.locator('.topbar-title').click();
  await expect(popup).not.toBeVisible();

  await page.goto('/admin/library');
  await page.getByRole('button', { name: '导入资料', exact: true }).first().click();
  const modal = page.getByRole('dialog', { name: '添加资料', exact: true });
  const modalHelp = modal.getByRole('button', { name: '资料导入说明', exact: true });
  await modalHelp.focus();
  await expect(
    page.locator('.help-tip-content').filter({ hasText: '基础解析在本地进行' }),
  ).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(
    page.locator('.help-tip-content').filter({ hasText: '基础解析在本地进行' }),
  ).not.toBeVisible();
  await expect(modal).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(modal).toHaveCount(0);
});

test('both areas keep routine explanations behind question icons while headings stay concise', async ({
  page,
}) => {
  for (const url of [
    '/',
    '/admin',
    '/library',
    '/admin/library',
    '/agents',
    '/admin/agents',
    '/skills',
    '/admin/skills',
    '/graph',
    '/admin/graph',
    '/artifacts',
    '/memories',
    '/admin/jobs',
    '/admin/models',
    '/admin/settings',
    '/admin/data',
  ]) {
    await page.goto(url);
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.locator('.page-description:visible')).toHaveCount(0);
    await expect(
      page.locator('.heading-with-help').first().locator('button.help-tip'),
    ).toBeVisible();
    await expect(page.locator('.help-tip-content:visible')).toHaveCount(0);
  }
  await page.goto('/library/not-existing-help-check');
  await expect(page.getByRole('alert').first()).toContainText('不存在');
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeVisible();
});

test('method explanations are independent of method selection and never submit a model call', async ({
  page,
  request,
}, info) => {
  const imported = await (
    await request.post('/api/v1/sources/paste', {
      data: {
        title: `问号提示验收 ${info.project.name} ${Date.now()}`,
        text: '第一章 原创提示测试\n先写下问题，再验证边界。',
        duplicate_action: 'copy',
      },
    })
  ).json();
  try {
    const mutations: string[] = [];
    page.on('request', (req) => {
      if (req.method() === 'POST' && req.url().endsWith('/distill')) mutations.push(req.url());
    });
    await page.goto('/admin/library/' + imported.source.id);
    await page.getByRole('button', { name: '蒸馏所选章节', exact: true }).click();
    const modal = page.getByRole('dialog', { name: '确认本次蒸馏', exact: true });
    const chosen = modal.getByRole('radio', { name: /仓颉/ });
    await expect(chosen).toBeChecked();
    const help = modal.getByRole('button', { name: /博览.*方法说明/ });
    await help.hover();
    await expect(page.locator('.help-tip-content').filter({ hasText: '调用量' })).toBeVisible();
    await help.click();
    await expect(chosen).toBeChecked();
    await expect(modal.getByRole('radio', { name: /博览/ })).not.toBeChecked();
    expect(mutations).toEqual([]);
  } finally {
    await request.delete(`/api/v1/sources/${imported.source.id}?mode=derived&history=redact`);
  }
});
