import { test, expect } from '@playwright/test';
import { VIEWPORTS } from './viewports';

test.use({ viewport: VIEWPORTS.desktop });

test('app loads and root element is present', async ({ page }) => {
  await page.goto('/');

  // The app container is always rendered regardless of backend availability
  const appContainer = page.locator('.app-container');
  await expect(appContainer).toBeVisible({ timeout: 10000 });
});
