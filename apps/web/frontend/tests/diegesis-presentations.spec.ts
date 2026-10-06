import { expect, test } from '@playwright/test';
import { startVaultServer, useRealVault, type VaultServer } from './support/vaultServer';

/**
 * The diegesis panel must reach a presentation of either rendering model.
 *
 * A document-model project has no `outputs/presentation/` directory and no
 * slides to count, so a card gated on a slide count rendered no link at all and
 * the presentation was unreachable from the graph. These run against the real
 * backend over a synthetic vault — `observatory` is a document-model project
 * and `alpha` a legacy slide project — so the `presentation_model` the card
 * reads is the one the real router emits, not a value this test supplied.
 */

let server: VaultServer;
test.beforeAll(async () => { server = await startVaultServer(); });
test.afterAll(async () => { await server?.stop(); });
test.beforeEach(async ({ context }) => { await useRealVault(context, server); });

const card = (page: import('@playwright/test').Page, name: string) =>
    page.locator('.thesis-card').filter({ hasText: name });

async function openDiegesis(page: import('@playwright/test').Page) {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/?diegesis=synthetic');
    await expect(page.getByRole('heading', { name: 'Linked Theses' })).toBeVisible();
}

test('a document-model thesis links to the route that serves its document', async ({ page }) => {
    await openDiegesis(page);

    const link = card(page, 'Observatory').getByRole('link', { name: 'View Presentation' });
    await expect(link).toHaveAttribute('href', /^\/presentations\?thesis=observatory/);

    // The link is only worth rendering if the destination opens the document,
    // so follow it: the player's cue readout proves the document was served.
    await link.click();
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
});

test('a legacy slides thesis keeps its counts and its existing destination', async ({ page }) => {
    await openDiegesis(page);

    const legacy = card(page, 'Alpha presentation');
    await expect(legacy).toContainText('2 slides');
    await expect(legacy).toContainText('2/2 with images');
    await expect(legacy.getByRole('link', { name: 'View Presentation' }))
        .toHaveAttribute('href', /^\/presentations\?thesis=alpha/);
});

test('a project with no presentation still offers no link', async ({ page }) => {
    await openDiegesis(page);

    const unwritten = card(page, 'Unwritten presentation');
    await expect(unwritten).toBeVisible();
    await expect(unwritten.getByRole('link', { name: 'View Presentation' })).toHaveCount(0);
});
