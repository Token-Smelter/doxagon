import { inflateSync } from 'node:zlib';
import { test, expect, type Locator, type Page } from '@playwright/test';
import { VIEWPORTS } from '../viewports';

const stats = { inbox_count: 2, phantasiai: { unprocessed: 1, processing: 1, processed: 1, failed: 1, archived: 1 }, doxai_count: 4, evidence_count: 3, edges_count: 2, diegeses_count: 1 };
const phantasiai = [
  { slug: 'active-phantasia', title: 'Active encounter', source: 'https://example.test/active', status: 'processing', encountered: '2026-08-27', doxai_count: 0, evidence_count: 0 },
  { slug: 'fixed-phantasia', title: 'Fixed encounter', source: 'https://example.test/fixed', status: 'processed', encountered: '2026-08-26', doxai_count: 2, evidence_count: 1 },
  { slug: 'pending-phantasia', title: 'Pending encounter', source: 'https://example.test/pending', status: 'unprocessed', encountered: '2026-08-25', doxai_count: 0, evidence_count: 0 },
  { slug: 'failed-phantasia', title: 'Failed encounter', source: 'https://example.test/failed', status: 'failed', encountered: '2026-08-24', doxai_count: 0, evidence_count: 0 },
  { slug: 'archived-phantasia', title: 'Archived encounter', source: 'https://example.test/archived', status: 'archived', encountered: '2026-08-23', doxai_count: 0, evidence_count: 0 },
];
const detail = { ...phantasiai[0], channel: 'rss', shared_by: null, tags: ['research'], extracted_doxai: [{ slug: 'd', belief: null }], extracted_evidence: [{ slug: 'evidence-one', assertion: 'Supporting record' }], content: 'A source-grounded note.' };

type PipelineOptions = {
  detailRequestFails?: boolean;
  extractionFails?: boolean;
};

async function mockPipeline(page: Page, options: PipelineOptions = {}) {
  await page.route('**/api/**', async route => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();
    const isDetailRequest = pathname.endsWith('/phantasiai/active-phantasia') && method === 'GET';
    const isExtractionRequest = pathname.endsWith('/phantasiai/active-phantasia/extract');

    if (isDetailRequest && options.detailRequestFails) return route.abort('failed');
    if (isExtractionRequest && options.extractionFails) {
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Extraction unavailable' }),
      });
    }

    const body = pathname.endsWith('/pipeline/stats') ? stats
      : pathname.endsWith('/phantasiai') && method === 'GET' ? phantasiai
      : pathname.endsWith('/evidence') ? []
      : isDetailRequest ? detail
      : isExtractionRequest ? { slug: 'active-phantasia', status: 'processed', created_doxai: ['claim-one'], created_evidence: ['evidence-one'], created_edges: 1, skipped_duplicates: 0, suggested_links: 0 }
      : pathname.endsWith('/phantasiai') && method === 'POST' ? { slug: 'created-phantasia', status: 'unprocessed' }
      : pathname.endsWith('/phantasiai/active-phantasia') && method === 'DELETE' ? { slug: 'active-phantasia', status: 'archived' }
      : {};
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
}

async function openPipeline(page: Page, view = '', options: PipelineOptions = {}) {
  await mockPipeline(page, options);
  await page.goto(`/pipeline${view}`);
  await expect(page.locator('.pipeline-page')).toBeVisible();
  await expect(page.getByText('Loading pipeline data…')).toBeHidden();
  if (view.includes('view=phantasiai')) await expect(page.getByRole('button', { name: 'Create phantasia' })).toBeVisible();
  else await expect(page.getByRole('heading', { name: 'Pipeline overview' })).toBeVisible();
}

function hasMultiplePixelColors(png: Buffer): boolean {
  const signatureLength = 8;
  let offset = signatureLength;
  let width = 0;
  let height = 0;
  let colorType = 0;
  const idat: Buffer[] = [];

  while (offset < png.length) {
    const length = png.readUInt32BE(offset);
    const type = png.subarray(offset + 4, offset + 8).toString('ascii');
    const data = png.subarray(offset + 8, offset + 8 + length);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      expect(data[8]).toBe(8);
      colorType = data[9];
      expect(data[12]).toBe(0);
    }
    if (type === 'IDAT') idat.push(data);
    offset += length + 12;
  }

  const bytesPerPixel = colorType === 6 ? 4 : 3;
  expect(colorType === 2 || colorType === 6).toBeTruthy();
  const stride = width * bytesPerPixel;
  const decompressed = inflateSync(Buffer.concat(idat));
  let cursor = 0;
  let previousRow = new Uint8Array(stride);
  let firstColor: string | undefined;

  for (let row = 0; row < height; row += 1) {
    const filter = decompressed[cursor++];
    const currentRow = new Uint8Array(stride);
    for (let column = 0; column < stride; column += 1) {
      const left = column >= bytesPerPixel ? currentRow[column - bytesPerPixel] : 0;
      const above = previousRow[column];
      const upperLeft = column >= bytesPerPixel ? previousRow[column - bytesPerPixel] : 0;
      const value = decompressed[cursor++];
      if (filter === 0) currentRow[column] = value;
      else if (filter === 1) currentRow[column] = (value + left) & 0xff;
      else if (filter === 2) currentRow[column] = (value + above) & 0xff;
      else if (filter === 3) currentRow[column] = (value + Math.floor((left + above) / 2)) & 0xff;
      else {
        const p = left + above - upperLeft;
        const pa = Math.abs(p - left);
        const pb = Math.abs(p - above);
        const pc = Math.abs(p - upperLeft);
        currentRow[column] = (value + (pa <= pb && pa <= pc ? left : pb <= pc ? above : upperLeft)) & 0xff;
      }
    }
    for (let column = 0; column < stride; column += bytesPerPixel) {
      const color = currentRow.subarray(column, column + bytesPerPixel).join(',');
      if (firstColor === undefined) firstColor = color;
      else if (color !== firstColor) return true;
    }
    previousRow = currentRow;
  }
  return false;
}

async function expectMobileTargets(controls: Locator) {
  const count = await controls.count();
  expect(count).toBeGreaterThan(0);
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    if (!await control.isVisible()) continue;
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
}

async function expectContrastAtLeast(page: Page, foregroundSelector: string, backgroundSelector: string, minimum: number) {
  const ratio = await page.locator(foregroundSelector).first().evaluate((element, backgroundSelector) => {
    const rgb = (value: string) => {
      const channels = value.match(/^rgba?\(\s*([\d.]+)(?:px|%)?[\s,]+([\d.]+)(?:px|%)?[\s,]+([\d.]+)(?:px|%)?/i)?.slice(1, 4);
      if (channels) return channels.map(Number);

      const srgb = value.match(/^color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)/i)?.slice(1, 4);
      if (srgb) return srgb.map(channel => Number(channel) * 255);

      throw new Error(`Unsupported resolved color: ${value}`);
    };
    const luminance = ([red, green, blue]: number[]) => [red, green, blue].map(channel => {
      const normalized = channel / 255;
      return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    }).reduce((total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index], 0);
    let background = element.closest(backgroundSelector) ?? document.querySelector(backgroundSelector);
    while (background && getComputedStyle(background).backgroundColor === 'rgba(0, 0, 0, 0)') {
      background = background.parentElement;
    }
    if (!background) throw new Error(`Missing opaque contrast background: ${backgroundSelector}`);
    const [foregroundStyle, backgroundStyle] = [getComputedStyle(element), getComputedStyle(background)];
    const [foreground, backgroundLuminance] = [luminance(rgb(foregroundStyle.color)), luminance(rgb(backgroundStyle.backgroundColor))];
    return {
      ratio: (Math.max(foreground, backgroundLuminance) + 0.05) / (Math.min(foreground, backgroundLuminance) + 0.05),
      foreground: foregroundStyle.color,
      background: backgroundStyle.backgroundColor,
    };
  }, backgroundSelector);
  expect(
    ratio.ratio,
    `${foregroundSelector} on ${backgroundSelector}: ${ratio.foreground} on ${ratio.background}`,
  ).toBeGreaterThanOrEqual(minimum);
}

test.describe('Pipeline behavior is independent of the backend', () => {
  test.use({ viewport: VIEWPORTS.mobile_medium });

  test('filters, selects, extracts, and retains its URL view', async ({ page }) => {
    await openPipeline(page, '?view=phantasiai');
    await page.getByRole('button', { name: 'processing', exact: true }).click();
    await expect(page.getByRole('button', { name: /Active encounter/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Fixed encounter/ })).toBeHidden();
    await page.getByRole('button', { name: /Active encounter/ }).click();
    await expect(page.getByRole('heading', { name: 'Active encounter' })).toBeVisible();
    await page.getByRole('button', { name: 'Extract doxai' }).click();
    await expect(page.getByText('doxai created')).toBeVisible();
    await expect(page).toHaveURL(/view=phantasiai/);
  });

  test('create form reports validation and supports keyboard escape', async ({ page }) => {
    await openPipeline(page, '?view=phantasiai');
    await page.getByRole('button', { name: 'Create phantasia' }).click();
    const dialog = page.getByRole('dialog', { name: 'New Phantasia' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Create phantasia' }).click();
    await expect(dialog.getByRole('alert')).toContainText('Source is required');
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
  });

  test('controls expose keyboard focus and state without color alone', async ({ page }) => {
    await openPipeline(page, '?view=phantasiai');
    const processing = page.getByRole('button', { name: 'processing', exact: true });
    await processing.focus();
    await expect(processing).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(processing).toHaveAttribute('aria-pressed', 'true');
    await expect(processing.locator('.filter-mark')).toBeVisible();
  });

  test('create dialog traps keyboard focus and restores its opener', async ({ page }) => {
    await openPipeline(page, '?view=phantasiai');
    const opener = page.getByRole('button', { name: 'Create phantasia' });
    await opener.click();
    const dialog = page.getByRole('dialog', { name: 'New Phantasia' });
    const source = dialog.getByLabel('Source (required)');
    const close = dialog.getByRole('button', { name: 'Close new phantasia form' });
    const submit = dialog.getByRole('button', { name: 'Create phantasia' });
    await expect(source).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(close).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(submit).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
  });

  test('semantic roles maintain AA contrast on cream and nigredo', async ({ page }) => {
    await openPipeline(page, '?view=phantasiai');
    for (const selector of ['.status.unprocessed', '.status.processing', '.status.processed', '.status.failed', '.status.archived', '.filter-btn.active', '.nav-tab.active', '.item', '.item-meta']) {
      await expectContrastAtLeast(page, selector, selector.includes('item') ? '.item' : selector, 4.5);
    }
    await page.getByRole('button', { name: 'Use nigredo ground' }).click();
    await expect(page.locator('body')).toHaveClass(/dox-invert/);
    await expect(page.locator('.item').first()).toHaveCSS('background-color', 'rgb(41, 36, 29)');
    for (const selector of ['.status.unprocessed', '.status.processing', '.status.processed', '.status.failed', '.status.archived', '.filter-btn.active', '.nav-tab.active', '.item', '.item-meta']) {
      await expectContrastAtLeast(page, selector, selector.includes('item') ? '.item' : selector, 4.5);
    }
    await page.getByRole('button', { name: 'Use cream ground' }).click();
    await page.getByRole('button', { name: 'Create phantasia' }).click();
    const dialog = page.getByRole('dialog', { name: 'New Phantasia' });
    await dialog.getByRole('button', { name: 'Create phantasia' }).click();
    await expectContrastAtLeast(page, '.error', '.error', 4.5);
    await expectContrastAtLeast(page, '.required', '.modal', 4.5);
  });

  test('detail fetch errors are legible on the running fill', async ({ page }) => {
    await openPipeline(page, '?view=phantasiai', { detailRequestFails: true });
    await page.getByRole('button', { name: /Active encounter/ }).click();
    await expect(page.getByRole('alert')).toContainText('Failed to load phantasia');
    await expectContrastAtLeast(page, '.state.error', '.state.error', 4.5);
  });

  test('extraction errors remain visible and actionable', async ({ page }) => {
    await openPipeline(page, '?view=phantasiai', { extractionFails: true });
    await page.getByRole('button', { name: /Active encounter/ }).click();
    await page.getByRole('button', { name: 'Extract doxai' }).click();
    await expect(page.getByRole('alert')).toContainText('Extraction unavailable');
    await expectContrastAtLeast(page, '.state.error', '.state.error', 4.5);
  });

  test('list detail and form controls meet mobile target size', async ({ page }) => {
    await openPipeline(page, '?view=phantasiai');
    await expectMobileTargets(page.locator('.pipeline-page').locator('button, a, input, textarea, select'));
    await page.getByRole('button', { name: /Active encounter/ }).click();
    await expect(page.getByRole('heading', { name: 'Active encounter' })).toBeVisible();
    await expectMobileTargets(page.locator('.pipeline-page').locator('button, a, input, textarea, select'));
    await page.getByRole('button', { name: 'Close phantasia detail' }).click();
    await page.getByRole('button', { name: 'Create phantasia' }).click();
    const dialog = page.getByRole('dialog', { name: 'New Phantasia' });
    await expect(dialog).toBeVisible();
    await expectMobileTargets(dialog.locator('button, input, textarea, select'));
  });
});

for (const [name, viewport] of Object.entries(VIEWPORTS)) {
  test(`pipeline has no horizontal document overflow at ${name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openPipeline(page, '?view=phantasiai');
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
  });
}

test.describe('Pipeline visual proof', () => {
  test.use({ viewport: VIEWPORTS.desktop });

  test('captures rendered cream and nigredo desktop surfaces', async ({ page }, testInfo) => {
    await openPipeline(page, '?view=phantasiai');
    await expect(page.locator('.item').first()).toHaveCSS('background-color', 'rgb(230, 219, 194)');
    const cream = await page.screenshot({ path: testInfo.outputPath('pipeline-1280x800-cream.png'), fullPage: false });
    expect(hasMultiplePixelColors(cream)).toBeTruthy();
    await page.getByRole('button', { name: 'Use nigredo ground' }).click();
    await expect(page.locator('body')).toHaveClass(/dox-invert/);
    await expect(page.locator('.pipeline-page')).toHaveCSS('background-color', 'rgb(22, 19, 15)');
    await expect(page.locator('.item').first()).toHaveCSS('background-color', 'rgb(41, 36, 29)');
    const nigredo = await page.screenshot({ path: testInfo.outputPath('pipeline-1280x800-nigredo.png'), fullPage: false });
    expect(hasMultiplePixelColors(nigredo)).toBeTruthy();
  });

  test('captures a rendered cream mobile surface', async ({ page }, testInfo) => {
    await page.setViewportSize(VIEWPORTS.mobile_medium);
    await openPipeline(page, '?view=phantasiai');
    const cream = await page.screenshot({ path: testInfo.outputPath('pipeline-375x667-cream.png'), fullPage: false });
    expect(hasMultiplePixelColors(cream)).toBeTruthy();
  });
});
