import { test as base, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const directory = process.env.MINDCHIME_DATA_DIR || path.resolve('../data');
export const accounts: { username: string; password: string; role: string }[] = JSON.parse(
  fs.readFileSync(path.join(directory, 'local-accounts.json'), 'utf8'),
);
export const test = base.extend<{ administrator: void }>({
  administrator: [
    async ({ context, request }, use) => {
      const admin = accounts.find((a) => a.username === 'admin')!;
      expect((await context.request.post('/api/v1/auth/login', { data: admin })).ok()).toBeTruthy();
      expect((await request.post('/api/v1/auth/login', { data: admin })).ok()).toBeTruthy();
      await use();
    },
    { auto: true },
  ],
});
export { expect };
