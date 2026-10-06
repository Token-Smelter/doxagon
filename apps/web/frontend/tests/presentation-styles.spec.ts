import { expect, test as base, type Page } from '@playwright/test';
import { selectFromRail } from './support/rail';
import { startVaultServer, useRealVault, type VaultServer } from './support/vaultServer';

// Every test owns its vault: edits and deletions must not change what another
// browser proof reads, regardless of the worker count or execution order.
const test = base.extend<{ vault: VaultServer }>({
    vault: async ({}, use) => {
        const server = await startVaultServer();
        try { await use(server); } finally { await server.stop(); }
    },
});

const REFERENCE = '01-opening · main · two.png';
const styleRow = (page: Page, id = 'ink') => page.locator(`[data-style="${id}"]`);
const generationStyles = (page: Page) => page.getByRole('group', { name: 'Styles for this generation' });

async function openEditor(page: Page) {
    await page.goto('/presentations');
    await selectFromRail(page, /Alpha/);
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(2);
    if ((page.viewportSize()?.width ?? 1440) < 768) {
        await page.getByRole('button', { name: 'Inspector', exact: true }).click();
    }
    await page.getByRole('tab', { name: 'Media', exact: true }).click();
}

async function createStyle(page: Page, name = 'ink', text = 'Black ink on warm paper.') {
    await page.getByLabel('Style name', { exact: true }).fill(name);
    await page.getByLabel('Style prompt', { exact: true }).fill(text);
    await page.getByRole('button', { name: 'Save style', exact: true }).click();
    await expect(page.getByTestId('deck-notice')).toHaveText(`Style ${name} saved`);
    await expect(styleRow(page, name)).toContainText(text);
}

test.beforeEach(async ({ page, vault }) => {
    await useRealVault(page.context(), vault);
});

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    test(`image styles survive reload, edit, and deletion at ${viewport.width}px`, async ({ page }) => {
        await page.setViewportSize(viewport);
        await openEditor(page);
        await expect(page.getByText('No image styles saved yet.')).toBeVisible();
        await expect(page.getByRole('button', { name: 'Save style', exact: true })).toBeDisabled();

        await page.getByRole('group', { name: 'Reference images', exact: true })
            .getByRole('checkbox', { name: REFERENCE, exact: true }).check();
        await createStyle(page);
        await expect(styleRow(page)).toContainText(REFERENCE);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
        // A reference cannot be retired while a saved style still uses it.
        const media = page.locator('li.asset').filter({ has: page.getByRole('heading', { name: REFERENCE, exact: true }) });
        await expect(media.getByRole('button', { name: 'Delete', exact: true })).toBeDisabled();

        await openEditor(page);
        await expect(styleRow(page)).toContainText('Black ink on warm paper.');
        await expect(styleRow(page)).toContainText(REFERENCE);
        await page.getByLabel('Style name', { exact: true }).fill('ink');
        await page.getByLabel('Style prompt', { exact: true }).fill('An accidental duplicate');
        await expect(page.getByText('A style with this name already exists.', { exact: false })).toBeVisible();
        await expect(page.getByRole('button', { name: 'Save style', exact: true })).toBeDisabled();
        await page.getByRole('button', { name: 'Cancel', exact: true }).click();

        await styleRow(page).getByRole('button', { name: 'Edit', exact: true }).click();
        await expect(page.getByLabel('Style name', { exact: true })).toBeDisabled();
        const reference = page.getByRole('group', { name: 'Reference images', exact: true })
            .getByRole('checkbox', { name: REFERENCE, exact: true });
        await expect(reference).toBeChecked();
        await reference.uncheck();
        await page.getByLabel('Style prompt', { exact: true }).fill('Blue ink with generous whitespace.');
        await page.getByRole('button', { name: 'Save style', exact: true }).click();
        await expect(styleRow(page)).toContainText('Blue ink with generous whitespace.');
        await expect(media.getByRole('button', { name: 'Delete', exact: true })).toBeEnabled();

        await openEditor(page);
        await expect(styleRow(page)).toContainText('Blue ink with generous whitespace.');
        await expect(styleRow(page)).not.toContainText(REFERENCE);
        await generationStyles(page).getByRole('checkbox', { name: 'ink', exact: true }).check();
        await styleRow(page).getByRole('button', { name: 'Delete', exact: true }).click();
        await expect(styleRow(page)).toHaveCount(0);
        await expect(generationStyles(page)).toHaveCount(0);
        // Recreating the same name must not silently reselect a deleted style.
        await createStyle(page);
        await expect(generationStyles(page).getByRole('checkbox', { name: 'ink', exact: true })).not.toBeChecked();
        await styleRow(page).getByRole('button', { name: 'Delete', exact: true }).click();
        await expect(styleRow(page)).toHaveCount(0);
        await openEditor(page);
        await expect(styleRow(page)).toHaveCount(0);

        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
        const save = await page.getByRole('button', { name: 'Save style', exact: true }).boundingBox();
        expect(save!.height).toBeGreaterThanOrEqual(viewport.width < 1024 ? 44 : 32);
        expect(save!.x).toBeGreaterThanOrEqual(0);
        expect(save!.x + save!.width).toBeLessThanOrEqual(viewport.width + 1);
    });
}

test('generation uses saved style text and references and keeps the original prompt after edits', async ({ page, vault }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openEditor(page);
    await page.getByRole('group', { name: 'Reference images', exact: true })
        .getByRole('checkbox', { name: REFERENCE, exact: true }).check();
    await createStyle(page);
    await createStyle(page, 'unused', 'This direction should not reach the prompt.');
    await generationStyles(page).getByRole('checkbox', { name: 'ink', exact: true }).check();
    await page.getByTestId('generation-label').fill('Styled landscape');
    await page.getByTestId('generation-alt').fill('A landscape in ink');
    await page.getByTestId('generation-description').fill('Rolling hills and a river.');
    await page.getByTestId('generate').click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Generation succeeded');
    await expect(page.locator('li.asset', { hasText: 'Styled landscape — variant 1' })).toContainText('succeeded');

    // Read the real server's durable result, beyond the success notice: both
    // the assembled prompt and the reference closure must come from the style.
    const read = async () => (await page.request.get(`${vault.base}/api/presentations/alpha`)).json();
    const view = await read();
    const generated = view.assets.find((item: any) => item.label === 'Styled landscape — variant 1');
    const reference = view.assets.find((item: any) => item.label === REFERENCE);
    expect(generated.generation.prompt).toContain('## Style: ink\nBlack ink on warm paper.');
    expect(generated.generation.prompt).toContain('Rolling hills and a river.');
    expect(generated.generation.prompt).not.toContain('This direction should not reach the prompt.');
    expect(generated.generation.prompt_references).toEqual([reference.id]);

    await styleRow(page).getByRole('button', { name: 'Edit', exact: true }).click();
    await page.getByLabel('Style prompt', { exact: true }).fill('A new style for future generations.');
    await page.getByRole('button', { name: 'Save style', exact: true }).click();
    await expect(styleRow(page)).toContainText('A new style for future generations.');
    expect((await read()).assets.find((item: any) => item.id === generated.id).generation).toEqual(generated.generation);

    await page.getByTestId('generation-label').fill('Updated landscape');
    await page.getByTestId('generate').click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Generation succeeded');
    expect((await read()).assets.find((item: any) => item.label === 'Updated landscape — variant 1').generation.prompt)
        .toContain('A new style for future generations.');
});

for (const operation of ['save', 'delete'] as const) {
    test(`a stale style ${operation} cannot overwrite a newer edit`, async ({ page, context }) => {
        await openEditor(page);
        await createStyle(page);
        const stale = await context.newPage();
        await openEditor(stale);
        if (operation === 'save') {
            await styleRow(stale).getByRole('button', { name: 'Edit', exact: true }).click();
            await stale.getByLabel('Style prompt', { exact: true }).fill('Unsaved stale draft');
        }
        await styleRow(page).getByRole('button', { name: 'Edit', exact: true }).click();
        await page.getByLabel('Style prompt', { exact: true }).fill('The newer saved direction');
        await page.getByRole('button', { name: 'Save style', exact: true }).click();
        await expect(styleRow(page)).toContainText('The newer saved direction');
        const revision = await page.getByTestId('deck-revision').textContent();

        if (operation === 'save') await stale.getByRole('button', { name: 'Save style', exact: true }).click();
        else await styleRow(stale).getByRole('button', { name: 'Delete', exact: true }).click();
        await expect(stale.getByTestId('deck-failure')).toContainText('PRES_REVISION_CONFLICT');
        if (operation === 'save') await expect(stale.getByLabel('Style prompt', { exact: true })).toHaveValue('Unsaved stale draft');
        await openEditor(stale);
        await expect(styleRow(stale)).toContainText('The newer saved direction');
        await expect(stale.getByTestId('deck-revision')).toHaveText(revision!);
    });
}

test('changing presentations clears style drafts and generation selections', async ({ page }) => {
    await openEditor(page);
    await createStyle(page);
    await generationStyles(page).getByRole('checkbox', { name: 'ink', exact: true }).check();
    await styleRow(page).getByRole('button', { name: 'Edit', exact: true }).click();
    await page.getByLabel('Style prompt', { exact: true }).fill('A draft for Alpha only');
    await selectFromRail(page, /Stock/);
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(5);
    await page.getByRole('tab', { name: 'Media', exact: true }).click();
    await expect(styleRow(page)).toHaveCount(0);
    await expect(page.getByLabel('Style name', { exact: true })).toHaveValue('');
    await expect(page.getByLabel('Style prompt', { exact: true })).toHaveValue('');
    await selectFromRail(page, /Alpha/);
    await page.getByRole('tab', { name: 'Media', exact: true }).click();
    await expect(styleRow(page)).toContainText('Black ink on warm paper.');
    await expect(generationStyles(page).getByRole('checkbox', { name: 'ink', exact: true })).not.toBeChecked();
});
