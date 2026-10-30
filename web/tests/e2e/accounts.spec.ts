import { test, expect } from '@playwright/test';
import { accounts } from './fixtures';
import AxeBuilder from '@axe-core/playwright';
import path from 'node:path';
import fs from 'node:fs';
async function loginUI(page: any, name: string) {
  const account = accounts.find((a) => a.role === name)!;
  await page.goto('/login');
  await page.getByRole('textbox', { name: '账号', exact: true }).fill(account.username);
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(account.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
}

test('login, roles, session reload, logout and ordinary-user navigation', async ({
  page,
  browserName,
}) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login/);
  await loginUI(page, 'user');
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('link', { name: '进入后台', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '去后台导入资料', exact: true })).toHaveCount(0);
  expect((await page.request.get('/api/v1/profiles')).status()).toBe(403);
  for (const target of ['/library', '/agents', '/skills', '/graph']) {
    await page.goto(target);
    await expect(page.locator('[data-area="front"]')).toBeVisible();
    await expect(
      page.getByRole('button', {
        name: /管理资料|管理智能体|管理方法|管理关系|去后台创建|去后台维护/,
      }),
    ).toHaveCount(0);
  }
  await page.goto('/admin/models');
  await expect(page).toHaveURL(/\/$/);
  await page.reload();
  await expect(page.locator('[data-area="front"]')).toBeVisible();
  await expect(page.locator('.overview-metrics')).toBeVisible();
  if (browserName === 'chromium')
    await page.screenshot({
      path: path.resolve('../docs/validation/accounts-user-light.png'),
      fullPage: true,
    });
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
  expect((await page.request.get('/api/v1/sources')).status()).toBe(401);
  const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  expect(accessibility.violations).toEqual([]);
  await loginUI(page, 'admin');
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole('link', { name: '发布管理', exact: true })).toBeVisible();
  await page.goto('/admin/thoughts');
  await page.getByRole('button', { name: '女娲思想蒸馏', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('switch')).not.toBeChecked();
  await dialog.getByRole('switch').click();
  await expect(dialog.getByRole('switch')).toBeChecked();
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('button', { name: '女娲思想蒸馏', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('switch')).not.toBeChecked();
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
  if (browserName === 'chromium') {
    await page.getByRole('button', { name: '切换到深色主题' }).click();
    await expect
      .poll(() =>
        page.getByRole('button', { name: '刷新', exact: true }).evaluate((el) => {
          const rgb = getComputedStyle(el).color.match(/\d+/g);
          return rgb ? Number(rgb[0]) : 0;
        }),
      )
      .toBeGreaterThan(120);
    await page.screenshot({
      path: path.resolve('../docs/validation/accounts-admin-dark.png'),
      fullPage: true,
    });
  }
});

test('administrator explicitly publishes dependencies and user practices without any Agent', async ({
  page,
  request,
}) => {
  const admin = accounts.find((a) => a.username === 'admin')!,
    user = accounts.find((a) => a.role === 'user')!;
  await request.post('/api/v1/auth/login', { data: admin });
  const imported = await (
    await request.post('/api/v1/sources/paste', {
      data: {
        title: '账号浏览器验收 ' + Date.now(),
        text: '第一章 方法\n记录一次实际观察。',
        duplicate_action: 'copy',
      },
    })
  ).json();
  const sid = imported.source.id;
  try {
    const card = await (
      await request.post('/api/v1/cards', {
        data: {
          title: '可独立实践的方法',
          data: {
            type: 'method',
            content: '记录一次实际观察。',
            source_ids: [sid],
            references: [],
          },
        },
      })
    ).json();
    const skill = await (
      await request.post('/api/v1/skills', {
        data: {
          title: '账号验收独立实践',
          data: {
            source_ids: [sid],
            card_ids: [card.id],
            inputs: ['当前问题'],
            steps: [{ title: '观察', instruction: '记录一次实际观察。', output: '实际记录' }],
            completion_criteria: '有实际记录',
          },
        },
      })
    ).json();
    await page.request.post('/api/v1/auth/login', { data: user });
    expect((await page.request.get('/api/v1/skills')).status()).toBe(200);
    expect(
      (await (await page.request.get('/api/v1/skills')).json()).some((s: any) => s.id === skill.id),
    ).toBe(false);
    for (const id of [sid, card.id, skill.id])
      expect((await request.post('/api/v1/publications/' + id)).ok()).toBeTruthy();
    await page.goto('/skills?selected=' + skill.id);
    await expect(
      page.getByRole('heading', { name: skill.title, exact: true }).first(),
    ).toBeVisible();
    await page.getByRole('button', { name: '开始实践', exact: true }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('引导智能体', { exact: true })).toHaveCount(0);
    await dialog.getByRole('textbox').fill('核对真实观察');
    const started = page.waitForResponse(
      (r) => r.url().endsWith('/skills/' + skill.id + '/runs') && r.request().method() === 'POST',
    );
    await dialog.getByRole('button', { name: '开始记录', exact: true }).click();
    expect((await started).ok()).toBeTruthy();
    await expect(page.getByText('记录一次实际观察。', { exact: true }).last()).toBeVisible();
    const runs = await (await page.request.get('/api/v1/runs')).json();
    const run = runs.find((r: any) => r.data.skill_id === skill.id);
    expect(run).toBeTruthy();
    fs.appendFileSync(
      path.resolve('../.runtime/account-e2e-records.jsonl'),
      JSON.stringify({ run_id: run.id }) + '\n',
    );
    expect(run.data.agent_id).toBeUndefined();
    const own = await page.request.post('/api/v1/runs/' + run.id + '/advance', {
      data: { answer: '观察已记录', use_ai: false },
    });
    expect(own.ok()).toBeTruthy();
    expect((await request.get('/api/v1/runs/' + run.id)).status()).toBe(404);
  } finally {
    await request.delete('/api/v1/sources/' + sid + '?mode=derived&history=redact');
  }
});

test('new administration pages are accessible in both themes', async ({ page }) => {
  await loginUI(page, 'admin');
  await expect(page).toHaveURL(/\/admin$/);
  for (const theme of ['light', 'dark']) {
    if (theme === 'dark') await page.getByRole('button', { name: '切换到深色主题' }).click();
    for (const [url, title] of [
      ['/admin/thoughts', '人物与思想蒸馏'],
      ['/admin/publications', '发布管理'],
    ]) {
      await page.goto(url);
      await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
      const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
      expect(result.violations).toEqual([]);
    }
  }
});
