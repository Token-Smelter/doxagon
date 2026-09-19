import { expect, test, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { startVaultServer, useRealVault, type VaultServer } from './support/vaultServer';

const FIXTURES = fileURLToPath(new URL('./fixtures/', import.meta.url));

let server: VaultServer;
test.beforeAll(async () => { server = await startVaultServer(); });
test.afterAll(async () => { await server?.stop(); });
test.beforeEach(async ({ context }) => { await useRealVault(context, server); });

async function openDocument(page: Page, name: string) {
    await page.goto('/presentations/document');
    await expect(page.getByLabel('Open local HTML')).toHaveAttribute('data-ready', 'true');
    await page.getByLabel('Open local HTML').setInputFiles(join(FIXTURES, name));
}

test('a cue with claims shows a chip per claim, labelled from the vault', async ({ page }) => {
    await openDocument(page, 'claims.html');
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 2');
    const popupPromise = page.waitForEvent('popup');
    await page.getByRole('button', { name: 'Speaker notes', exact: true }).click();
    const popup = await popupPromise;
    await expect(popup.getByTestId('claim-chip')).toHaveText(['Validators serve their master', 'Households verify high-risk…']);
});

test('a malformed claim id is refused with the bridge handshake refusal', async ({ page }) => {
    await openDocument(page, 'claims-malformed.html');
    await expect(page.getByRole('alert')).toHaveText('The document sent an invalid or mismatched bridge handshake.');
    await expect(page.getByRole('button', { name: 'Speaker notes', exact: true })).toBeDisabled();
});

test('a cue declaring more claims than the cap is refused before any label is fetched', async ({ page }) => {
    const requested: string[] = [];
    await page.route('**/doxai/*/label', async (route) => { requested.push(route.request().url()); await route.fallback(); });
    await openDocument(page, 'claims-overflow.html');
    await expect(page.getByRole('alert')).toHaveText('The document sent an invalid or mismatched bridge handshake.');
    await expect(page.getByRole('button', { name: 'Speaker notes', exact: true })).toBeDisabled();
    expect(requested).toEqual([]);
});
