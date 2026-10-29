import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import path from 'node:path';

test('six method choices submit a book and prompt without starting a paid call', async ({
  page,
  request,
}, info) => {
  const imported = await (
    await request.post('/api/v1/sources/paste', {
      data: {
        title: `方法界面 ${info.project.name} ${Date.now()}`,
        text: '第一章 试验\n这是用户原创的界面测试资料，应保留来源和边界。',
      },
    })
  ).json();
  const sid = imported.source.id;
  let submitted: any;
  try {
    await page.route(`**/api/v1/sources/${sid}/distill`, async (route) => {
      submitted = route.request().postDataJSON();
      await route.fulfill({ json: { id: 'ui-contract-only', status: 'queued', data: {} } });
    });
    await page.goto('/library/' + sid);
    await page.getByRole('button', { name: '蒸馏所选章节', exact: true }).click();
    const modal = page.getByRole('dialog', { name: '确认本次蒸馏' });
    await expect(modal.getByRole('radio')).toHaveCount(6);
    await expect(modal.getByRole('radio', { name: /仓颉/ })).toBeChecked();
    await modal.getByRole('radio', { name: /博览/ }).check();
    await modal
      .getByPlaceholder('你希望从这份资料中重点理解什么？')
      .fill('只提取本书的判断标准与边界。');
    const accessibility = await new AxeBuilder({ page })
      .include('.n-modal')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    expect(accessibility.violations).toEqual([]);
    await modal
      .getByRole('button', { name: /确认|开始/ })
      .last()
      .click();
    await expect.poll(() => submitted?.method_id).toBe('bolan');
    expect(submitted.prompt).toBe('只提取本书的判断标准与边界。');
    expect(submitted.chapter_ids).toEqual(imported.chapters.map((c: any) => c.id));
  } finally {
    await request.delete(`/api/v1/sources/${sid}?mode=derived&history=redact`);
  }
});

test('real distillation result shows extensions, evidence and export in both themes', async ({
  page,
  request,
  browserName,
}) => {
  const sources = await (await request.get('/api/v1/sources')).json();
  const source = sources.find((s: any) => s.data.demo && s.title.includes('小步验证'));
  expect(source).toBeTruthy();
  const results = await (await request.get('/api/v1/distillations?source_id=' + source.id)).json();
  const result = results.find(
    (r: any) => r.data.method_id === 'cangjie' && r.status === 'completed',
  );
  expect(result, 'Run scripts/validate_distillation.py before the browser acceptance').toBeTruthy();
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/library/' + source.id);
  await page.getByRole('tab', { name: '蒸馏结果', exact: true }).click();
  const row = page.locator('.result-row').filter({ hasText: '仓颉' }).first();
  await row.getByRole('button', { name: '查看结果', exact: true }).click();
  const modal = page.getByRole('dialog', { name: '蒸馏结果与证据' });
  await expect(modal.getByRole('heading', { name: '方法特色成果', exact: true })).toBeVisible();
  await expect(
    modal.getByText('外部书评与联网核验未执行。', { exact: false }).first(),
  ).toBeVisible();
  await expect(modal.getByRole('button', { name: /核对原文/ }).first()).toBeVisible();
  const accessibility = await new AxeBuilder({ page })
    .include('.n-modal')
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  if (browserName === 'chromium')
    await page.screenshot({
      path: path.resolve('../docs/validation/distillation-results-light.png'),
      animations: 'disabled',
    });
  const exportResponse = await request.get(
    `/api/v1/export?kind=distillation&id=${result.id}&format=markdown`,
  );
  expect(exportResponse.ok()).toBeTruthy();
  expect(await exportResponse.text()).toContain('方法特色成果');
  await page.keyboard.press('Escape');
  await expect(modal).toHaveCount(0);
  await page.getByRole('button', { name: /切换到.*主题/ }).click();
  await row.getByRole('button', { name: '查看结果', exact: true }).click();
  await expect(modal.getByRole('heading', { name: '资料总览', exact: true })).toBeVisible();
  if (browserName === 'chromium')
    await page.screenshot({
      path: path.resolve('../docs/validation/distillation-results-dark.png'),
      animations: 'disabled',
    });
  expect(errors).toEqual([]);
});

test('Agent result selection exposes only the selected result cards', async ({ page, request }) => {
  const sources = await (await request.get('/api/v1/sources')).json();
  const source = sources.find((s: any) => s.data.demo && s.title.includes('小步验证'));
  const results = await (await request.get('/api/v1/distillations?source_id=' + source.id)).json();
  const result = results.find(
    (r: any) => r.data.method_id === 'cangjie' && r.status === 'completed',
  );
  const detail = await (await request.get('/api/v1/distillations/' + result.id)).json();
  const expected = detail.cards
    .filter((c: any) => c.status !== 'disabled')
    .map((c: any) => c.title);
  expect(expected.length).toBeGreaterThan(0);
  await page.goto('/library/' + source.id);
  await page.getByRole('tab', { name: '蒸馏结果', exact: true }).click();
  await page
    .locator('.result-row')
    .filter({ hasText: '仓颉' })
    .first()
    .getByRole('button', { name: '查看结果', exact: true })
    .click();
  await page.getByRole('button', { name: '用此结果生成 Agent', exact: true }).click();
  const modal = page.getByRole('dialog', { name: '从知识生成思想智能体', exact: true });
  await expect(modal).toBeVisible();
  await modal
    .locator('.n-form-item')
    .filter({ hasText: '限定知识卡（可选）' })
    .locator('.n-select')
    .click();
  const input = modal.getByLabel('限定知识卡（可选）', { exact: true });
  for (const title of expected) {
    await input.fill(title);
    await expect(page.locator('.n-base-select-option__content')).toContainText([title]);
  }
  const other = results.find(
    (r: any) => r.data.method_id === 'book-to-skill' && r.status === 'completed',
  );
  const otherDetail = await (await request.get('/api/v1/distillations/' + other.id)).json();
  const disallowed = otherDetail.cards.find((c: any) => !expected.includes(c.title));
  expect(disallowed).toBeTruthy();
  await input.fill(disallowed.title);
  await expect(page.locator('.n-base-select-option__content')).toHaveCount(0);
});
