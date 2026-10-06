import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { inflateRawSync } from 'node:zlib';
import { selectFromRail } from './support/rail';
import { startVaultServer, useRealVault, type VaultServer } from './support/vaultServer';

/**
 * Integration proof for the primary presentation editor and viewer.
 *
 * Nothing here is stubbed. `support/vault_server.py` serves the production
 * application over a synthetic legacy vault, so the project rail reads the real
 * thesis router, selecting a presentation runs the real migrator against a real
 * legacy tree, and every Step, Section, media, source, session, and export call
 * is answered by `doxagon.presentations.api`. A shape this suite asserts is a
 * shape a producer really emits.
 */

const SCREENSHOTS = fileURLToPath(
    new URL('../../../../docs/images/presentation-workspace', import.meta.url),
);
const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

// The ids the migrator mints for the synthetic vault's two legacy slides
// (`migration.checkpoint_id_for`). Naming them keeps the assertions about the
// real migration output rather than about whatever happens to be first.
const FIRST = 'slide-01-opening';
const SECOND = 'slide-02-market';

// The labels `migration.py` mints for the synthetic vault's four legacy
// candidates, and the one no legacy slide had selected.
const MIGRATED_MEDIA = [
    '01-opening · main · one.png',
    '01-opening · main · two.png',
    '02-market · main · one.png',
    '02-market · main · two.png',
];
const SPARE_MEDIA = '01-opening · main · two.png';

let server: VaultServer;

// Generation and editing tests mutate the vault. Sharing it across tests makes
// the gallery and revision assertions depend on which tests ran beforehand.
test.beforeEach(async () => {
    server = await startVaultServer();
});

test.afterEach(async () => {
    await server?.stop();
});

async function openWorkspace(page: Page, viewport = DESKTOP) {
    await page.setViewportSize(viewport);
    await useRealVault(page.context(), server);
    await page.goto('/presentations');
    await selectFromRail(page, /Alpha/);
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(2);
    await expect(page.getByTestId('deck-revision')).toContainText('sha256:');
}

// The outline entry, not the realm: the runtime's mount also carries the id it
// is currently presenting, and conflating the two would assert on the wrong
// element.
const outlineItem = (page: Page, id: string) => page.locator(`.outline-select[data-checkpoint="${id}"]`);

/**
 * The visible text of the editor, minus every explicitly advanced region.
 *
 * `innerText` would fold in a textarea's author bytes and a collapsed
 * disclosure's contents, so the walk skips form fields, hidden subtrees, and
 * anything marked `data-advanced` — which is exactly the developer surface
 * allowed to name the storage contract (`Checkpoint ID`, registered paths,
 * refusal codes, and the stored identifier a route addresses).
 */
const PRODUCT_TEXT = `(() => {
    const parts = [];
    const walk = (node) => {
        if (node.nodeType === Node.TEXT_NODE) { parts.push(node.nodeValue); return; }
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        if (node.dataset && node.dataset.advanced === 'true') return;
        if (['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'IFRAME'].includes(node.tagName)) return;
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return;
        for (const child of node.childNodes) walk(child);
    };
    walk(document.querySelector('main'));
    return parts.join(' ');
})()`;

/** The internal contract words that must not reach a product surface. */
const INTERNAL_VOCABULARY: [string, RegExp][] = [
    ['checkpoint', /\bcheckpoints?\b/i],
    ['edge', /\bedges?\b/i],
    ['capability', /\bcapabilit(y|ies)\b/i],
    ['asset', /\bassets?\b/i],
    ['agent', /\bagents?\b/i],
    ['group', /\bgroups?\b/i],
];

/** Every inspector tab this workspace offers, in product language. */
const TAB_LABELS = [
    'Overview','Source', 'Transitions', 'Permissions', 'Sections', 'Media', 'Notes', 'Edit with AI'];

/**
 * One member of a ZIP the server built, decompressed here.
 *
 * `_archive` writes each member with its sizes in the local header, so the
 * entry is found by its name and inflated without a ZIP library. Reading the
 * real bytes is the point: a manifest the browser could have invented would
 * prove nothing about the capture.
 */
function zipMember(archive: Buffer, name: string): Buffer {
    const wanted = Buffer.from(name, 'utf-8');
    for (let at = 0; at + 30 <= archive.length; at += 1) {
        if (archive.readUInt32LE(at) !== 0x04034b50) continue;
        const nameLength = archive.readUInt16LE(at + 26);
        const body = at + 30 + nameLength + archive.readUInt16LE(at + 28);
        if (!archive.subarray(at + 30, at + 30 + nameLength).equals(wanted)) continue;
        const bytes = archive.subarray(body, body + archive.readUInt32LE(at + 18));
        return archive.readUInt16LE(at + 8) === 0 ? Buffer.from(bytes) : inflateRawSync(bytes);
    }
    throw new Error(`the archive carries no member ${name}`);
}

test('selecting a real vault presentation opens its migrated Step workspace', async ({ page }) => {
    await openWorkspace(page);

    // The Steps are the migrator's output for the real legacy slides, not a
    // synthetic fixture and not a detached global workspace.
    await expect(outlineItem(page, FIRST)).toContainText('Opening');
    await expect(outlineItem(page, SECOND)).toContainText('Market');
    await expect(page.getByTestId('deck-runtime')).not.toHaveText('—');
    // The workspace the editor mutates is addressed by the selected presentation.
    await expect(page.locator('[data-presentation="alpha"]')).toHaveCount(1);
});

test('an existing numbered deck opens without a separate slide order and survives refresh', async ({ page }) => {
    await useRealVault(page.context(), server);
    await page.goto('/presentations?thesis=numbered');
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(5);
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-00-opening-step-0');
    await page.getByRole('button', { name: 'Slide 2: Motion choreography', exact: true }).click();
    await outlineItem(page, 'slide-01-motion-step-0').click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-01-motion-step-0');
    const revision = await page.getByTestId('deck-revision').textContent();

    await page.reload();

    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(5);
    await expect(page.getByTestId('deck-revision')).toHaveText(revision!);
    await expect(page.getByTestId('migration-blockers')).toHaveCount(0);
    await page.goto('/present/numbered');
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-00-opening-step-0');
});

test('the canvas is the shared Step runtime under a server-issued cursor', async ({ page }) => {
    await openWorkspace(page);

    await expect(page.getByTestId('preview-checkpoint')).toHaveText(FIRST);
    const opening = await page.getByTestId('preview-cursor').textContent();

    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText(SECOND);
    await expect(page.getByTestId('preview-cursor')).not.toHaveText(opening ?? '');

    // Back is a reversible traversal to the registered endpoint, not a counter.
    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText(FIRST);

    // Selecting in the outline is the same absolute seek through the session.
    await outlineItem(page, SECOND).click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText(SECOND);
    await expect(page.getByTestId('preview-signature')).toContainText('fnv1a32:');
});

test('stock choreography supports absolute seek and reversible Back', async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await useRealVault(page.context(), server);
    await page.goto('/presentations');
    await selectFromRail(page, /Stock/);
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(5);

    const state = () => page.frameLocator('.realm iframe').locator('#doxagon-checkpoint-root').evaluate((root) => ({
        html: root.innerHTML,
        step: (root as HTMLElement).dataset.step,
        steps: (root as HTMLElement).dataset.steps,
    }));
    const select = async (id: string) => {
        await page.locator(`.outline-select[data-checkpoint="${id}"]`).click();
        await expect(page.getByTestId('preview-checkpoint')).toHaveText(id);
    };

    await select('slide-opening-step-1');
    const directOne = await state();
    await select('slide-opening-step-2');
    const directTwo = await state();

    await select('slide-opening-step-0');
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-opening-step-1');
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-opening-step-2');
    expect(await state()).toEqual(directTwo);

    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-opening-step-1');
    expect(await state()).toEqual(directOne);
    expect(directTwo).toMatchObject({ step: '2', steps: '3' });
});

test('a Step selected while the session opens remains selected', async ({ page }) => {
    let release!: () => void;
    let opening!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const started = new Promise<void>((resolve) => { opening = resolve; });
    await useRealVault(page.context(), server);
    await page.route('**/api/presentations/stock/sessions', async (route) => {
        opening();
        await held;
        await route.fallback();
    });
    await page.goto('/presentations');
    await selectFromRail(page, /Stock/);
    await started;
    const wanted = 'slide-opening-step-1';
    try {
        await outlineItem(page, wanted).click();
        await expect(outlineItem(page, wanted)).toHaveAttribute('aria-current', 'true');
    } finally {
        release();
    }
    await expect(page.getByTestId('preview-checkpoint')).toHaveText(wanted);
    await expect(outlineItem(page, wanted)).toHaveAttribute('aria-current', 'true');
});

test('the presenter console reads a deck slide by slide', async ({ page, context }) => {
    await page.setViewportSize(DESKTOP);
    await useRealVault(page.context(), server);
    await page.goto('/presentations');
    await selectFromRail(page, /Stock/);
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(5);

    const [presenter] = await Promise.all([
        context.waitForEvent('page'),
        page.getByTestId('present').click(),
    ]);

    // Two legacy slides holding five Steps between them. The console groups the
    // Steps under the slide that owns each one, because a presenter navigates
    // the slide as much as the Step.
    const steps = presenter.getByTestId('presenter-steps');
    await expect(steps.locator('li')).toHaveCount(5);
    await expect(steps.locator('h3')).toHaveCount(2);
    await expect(steps.locator('h3').first()).toContainText('Opening choreography');
    await expect(presenter.getByTestId('presenter-position')).toHaveText('Slide 1 of 2 · step 1 of 3');
    await expect(presenter.getByTestId('presenter-next')).toContainText('Next step');

    // The last Step of a slide advances into the next slide, and says so rather
    // than reporting one more step of the slide being left.
    await presenter.locator('[data-checkpoint="slide-opening-step-2"]').click();
    await expect(presenter.getByTestId('presenter-position')).toHaveText('Slide 1 of 2 · step 3 of 3');
    await expect(presenter.getByTestId('presenter-next')).toContainText('Next slide');

    await presenter.getByRole('button', { name: 'Next' }).click();
    await expect(presenter.getByTestId('presenter-position')).toHaveText('Slide 2 of 2 · step 1 of 2');
});

test('a deck that returns to a slide numbers it once', async ({ page, context }) => {
    // Its own copy of the stock shape: this is the one test that reorders a
    // deck, and the shared `stock` tree decides what other tests read.
    await page.setViewportSize(DESKTOP);
    await useRealVault(page.context(), server);
    await page.goto('/presentations');
    await selectFromRail(page, /Outline/);
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(5);

    // Send the opening slide's last Step past the second slide, so the deck
    // plays slide 1, slide 2, and slide 1 again.
    const trailing = 'slide-opening-step-2';
    const response = await page.request.get(`${server.base}/api/presentations/outline`);
    const view = await response.json();
    const reordered = await page.request.put(`${server.base}/api/presentations/outline/checkpoint-order`, {
        headers: { 'If-Match': `"${view.revision}"` },
        data: { checkpoint_order: [...view.checkpoint_order.filter((id: string) => id !== trailing), trailing] },
    });
    expect(reordered.ok()).toBeTruthy();
    await page.reload();
    await expect(page.getByTestId('checkpoint-outline').locator('li').last().locator('button')).toHaveAttribute('data-checkpoint', trailing);

    const [presenter] = await Promise.all([
        context.waitForEvent('page'),
        page.getByTestId('present').click(),
    ]);

    // Three runs, two slides. The slide the deck comes back to keeps the number
    // it was given the first time, and the total counts slides rather than runs.
    const heads = presenter.getByTestId('presenter-steps').locator('.run-head .run-index');
    await expect(heads).toHaveText(['1', '2', '1']);
    await presenter.locator(`[data-checkpoint="${trailing}"]`).click();
    await expect(presenter.getByTestId('presenter-position')).toHaveText('Slide 1 of 2');
});

test('every migrated candidate is an equal first-class media asset', async ({ page }) => {
    await openWorkspace(page);
    await page.getByRole('tab', { name: 'Media' }).click();

    // Two legacy slides × two candidates: the unselected ones survived too.
    // Asserted by identity rather than by a total, so a media item another test
    // generated or retired cannot make this pass or fail for the wrong reason.
    for (const label of MIGRATED_MEDIA) {
        await expect(page.locator('li.asset', { hasText: label })).toHaveCount(1);
    }
    const media = page.getByTestId('asset-grid').locator('li.asset');
    // Label and provenance survived the migration for every candidate.
    await expect(media.first()).toContainText('01-opening · main');
    await expect(media.first()).toContainText('imported');

    // Nothing in the primary editor renders a primary/selected/display choice.
    const rendered = await page.locator('main').innerHTML();
    expect(rendered).not.toMatch(/is[_-]?primary|primary image|selected image|display image/i);

    const first = media.first();
    await expect(first.getByRole('button', { name: /Use in this step|Stop using here/ })).toBeVisible();
    // Delete is refused while a Step still uses the asset: deletion is safe by
    // construction rather than by warning.
    const used = page.locator('li.asset', { hasText: 'one.png' }).first();
    await expect(used.getByRole('button', { name: 'Delete' })).toBeDisabled();
});

test('media is used, released, and retired through the hosted producer', async ({ page }) => {
    await openWorkspace(page);
    const revision = async () => (await page.getByTestId('deck-revision').textContent()) ?? '';
    await outlineItem(page, FIRST).click();
    await page.getByRole('tab', { name: 'Media' }).click();

    // A migrated candidate the legacy tree never selected: no Step uses it yet.
    const spare = page.locator('li.asset', { hasText: SPARE_MEDIA }).first();
    await expect(spare).toContainText('no step');
    const opened = await revision();

    // Using media is a promotion: the reference and the revision both move.
    await spare.getByRole('button', { name: 'Use in this step' }).click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Added to this step');
    await expect(spare).toContainText(FIRST);
    expect(await revision()).not.toBe(opened);
    // The stored step includes it, and deletion is now refused.
    const stored = await (await page.request.get(`${server.base}/api/presentations/alpha`)).json();
    expect(stored.checkpoints.find((item: { id: string }) => item.id === FIRST).assets).toHaveLength(2);
    await expect(spare.getByRole('button', { name: 'Delete' })).toBeDisabled();

    // Releasing it is the same promotion in reverse.
    const used = await revision();
    await spare.getByRole('button', { name: 'Stop using here' }).click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Removed from this step');
    await expect(spare).toContainText('no step');
    expect(await revision()).not.toBe(used);

    // An unreferenced asset can be retired, and then it is gone from the revision.
    await spare.getByRole('button', { name: 'Delete' }).click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Media deleted');
    await expect(page.locator('li.asset', { hasText: SPARE_MEDIA })).toHaveCount(0);
});

test('generation is authored, executed, and retried from the primary editor', async ({ page }) => {
    await openWorkspace(page);
    await outlineItem(page, SECOND).click();
    await page.getByRole('tab', { name: 'Media' }).click();
    const media = page.getByTestId('asset-grid').locator('li.asset');
    const before = await media.count();

    // The configured backend renders 16:9 and refuses anything else, so this
    // request fails on the backend's own terms and lands on a durable record.
    await page.getByTestId('generation-label').fill('Market portrait');
    await page.getByTestId('generation-alt').fill('A portrait of the market');
    await page.getByTestId('generation-description').fill('A tall chart of the market.');
    await page.getByTestId('generation-aspect').selectOption('9:16');
    await page.getByTestId('generate').click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Generation failed');

    const failed = page.getByTestId('job-list').locator('li[data-status="failed"]').first();
    await expect(failed).toContainText('PRES_GENERATION_FAILED');
    await expect(failed).toContainText('16:9');
    await expect(failed).toContainText('attempt 1');

    // Retry is offered because the job is failed, and clicking it executes the
    // retry rather than leaving a pending record behind.
    await failed.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Retry failed');
    await expect(page.getByTestId('job-list').locator('li[data-status="failed"]')).toContainText([
        /attempt 1/,
        /attempt 2/,
    ]);

    // The same authoring in a framing the backend renders admits every variant
    // as its own equal asset, and a succeeded job offers no retry.
    await page.getByTestId('generation-label').fill('Market chart');
    await page.getByTestId('generation-alt').fill('A chart of the market');
    await page.getByTestId('generation-description').fill('A wide chart of the market.');
    await page.getByTestId('generation-aspect').selectOption('16:9');
    await page.getByTestId('generation-variants').fill('2');
    await page.getByTestId('generate').click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Generation succeeded');

    expect(await media.count()).toBe(before + 2);
    const generated = page.locator('li.asset', { hasText: 'Market chart — variant 1' }).first();
    await expect(generated).toContainText('generated');
    await expect(generated).toContainText('image-generation/1');
    await expect(generated).toContainText('succeeded');
    const succeeded = page.getByTestId('job-list').locator('li[data-status="succeeded"]').first();
    await expect(succeeded.getByRole('button', { name: 'Retry' })).toHaveCount(0);
});

test('the editor mutates Steps, Sections, and source on the selected presentation', async ({ page }) => {
    await openWorkspace(page);
    const revision = async () => (await page.getByTestId('deck-revision').textContent()) ?? '';
    const before = await revision();

    // Label a Step.
    await outlineItem(page, FIRST).click();
    await page.getByTestId('checkpoint-label').fill('Opening — revised');
    await page.getByTestId('checkpoint-label').blur();
    await expect(page.getByTestId('deck-notice')).toHaveText('Label saved');
    await expect(outlineItem(page, FIRST)).toContainText('Opening — revised');
    expect(await revision()).not.toBe(before);

    // Add a Step, then retire it. Both are promotions of a validated candidate.
    await page.getByTestId('new-step-label').fill('Interlude');
    await page.getByTestId('add-step').click();
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(3);
    await expect(outlineItem(page, 'interlude')).toContainText('Interlude');
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('interlude');
    await page.reload();
    await expect(outlineItem(page, 'interlude')).toBeVisible();
    await outlineItem(page, 'interlude').click();
    await page.getByRole('tab', { name: 'Source', exact: true }).click();
    await page.getByRole('button', { name: 'Delete Interlude' }).click();
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(2);

    await outlineItem(page, FIRST).click();
    await expect(page.getByRole('button', { name: /^Move .+ (earlier|later)$/ })).toHaveCount(0);

    // Sections group Steps and can carry an export boundary, nothing else.
    await page.getByRole('tab', { name: 'Sections' }).click();
    await page.getByTestId('group-id').fill('act-one');
    await page.getByTestId('group-label').fill('Act one');
    await page.getByTestId('group-save').click();
    await expect(page.getByTestId('group-list')).toContainText('Act one');
    await page.locator('[data-group="act-one"]').getByRole('button', { name: 'Add here' }).click();
    await expect(page.locator('[data-group="act-one"]')).toContainText('1 step');
    await page.locator('[data-group="act-one"]').getByRole('button', { name: 'Not an export boundary' }).click();
    await expect(page.locator('[data-group="act-one"]')).toContainText('Export boundary');

    // Raw source stays editable, and saving promotes a new revision.
    await page.getByRole('tab', { name: 'Source' }).click();
    await page.locator('[data-role="styles"]').click();
    const promoted = await revision();
    await page.getByTestId('source-editor').fill('.checkpoint { padding: 3rem; }\n');
    await page.getByRole('button', { name: 'Validate and promote' }).click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Saved styles');
    expect(await revision()).not.toBe(promoted);

    // Notes are authored in product vocabulary and travel in the same revision.
    await page.getByRole('tab', { name: 'Notes' }).click();
    await page.getByTestId('notes-editor').fill('Say the market number first.\n');
    await page.getByTestId('save-notes').click();
    await expect(page.getByTestId('deck-notice')).toHaveText('Saved notes');
});

test('an AI edit is scoped to one Step and shows before and after evidence', async ({ page }) => {
    await openWorkspace(page);
    await outlineItem(page, SECOND).click();
    await page.getByRole('tab', { name: 'Edit with AI' }).click();
    await page.getByRole('button', { name: /Edit .* with AI/ }).click();

    await expect(page.getByTestId('agent-scope')).toHaveText(SECOND);
    await expect(page.getByTestId('agent-before-digest')).not.toHaveText('—');
    const beforeDigest = (await page.getByTestId('agent-before-digest').textContent()) ?? '';
    const beforePreview = await page.getByTestId('agent-before-preview').textContent();

    // The operator supplies an instruction and nothing else. The proposed bytes
    // are written by the authoring backend the server was configured with, from
    // the task context the server issued — this test never types them.
    await page.getByTestId('agent-instruction').fill('Say it for investors');
    await page.getByTestId('agent-propose').click();

    await expect(page.getByTestId('agent-proposal-author')).toContainText('subprocess:agent_author.py');
    await expect(page.getByTestId('agent-proposal-role')).toHaveText('document');
    await expect(page.getByTestId('agent-proposal-digest')).not.toHaveText('');
    // Composed from the issued task's own checkpoint and the before-state digest
    // the server published — neither of which this test typed anywhere.
    await expect(page.getByTestId('agent-draft')).toHaveValue(
        new RegExp(`authored-by-backend for ${SECOND} against ${beforeDigest.slice(0, 12)}`),
    );
    await expect(page.getByTestId('agent-draft')).toHaveValue(/Say it for investors/);

    await page.getByRole('button', { name: 'Approve and promote' }).click();

    await expect(page.getByTestId('agent-outcome-after')).toContainText('sha256:');
    await expect(page.getByTestId('agent-outcome-before-preview')).toHaveText(beforePreview ?? '');
    await expect(page.getByTestId('agent-outcome-after-preview')).not.toHaveText(beforePreview ?? '');

    // The task retires the moment the shown Step changes.
    await outlineItem(page, FIRST).click();
    await expect(page.getByTestId('agent-context')).toHaveCount(0);
});

test('presenter and audience play back one server session', async ({ page, context }) => {
    await openWorkspace(page);
    const [presenter] = await Promise.all([
        context.waitForEvent('page'),
        page.getByTestId('present').click(),
    ]);

    // The audience display in this window follows the shared session; it offers
    // no control of its own.
    const audience = page.getByTestId('audience-display');
    await expect(audience).toBeVisible();
    await expect(audience.getByRole('button', { name: 'Next' })).toHaveCount(0);

    await expect(presenter.getByTestId('presenter-steps').locator('li')).toHaveCount(2);
    const opening = await audience.locator('[data-checkpoint]').first().getAttribute('data-checkpoint');
    const openingNotes = await presenter.getByTestId('presenter-notes').textContent();
    const openingNext = await presenter.getByTestId('presenter-next').textContent();

    await presenter.getByRole('button', { name: 'Next' }).click();

    // A second client moved the server cursor; this one adopted the snapshot.
    await expect(audience.locator('[data-checkpoint]').first()).not.toHaveAttribute(
        'data-checkpoint',
        opening ?? '',
    );
    const current = await audience.locator('[data-checkpoint]').first().getAttribute('data-checkpoint');

    // The presenter's own readouts follow every issued snapshot, not just the
    // one the session opened with: notes, the next step, and the current-step
    // marker all move with the cursor the server now holds.
    await expect(presenter.getByTestId('presenter-notes')).not.toHaveText(openingNotes ?? '');
    await expect(presenter.getByTestId('presenter-next')).not.toHaveText(openingNext ?? '');
    await expect(presenter.locator('[data-checkpoint][aria-current="true"]')).toHaveAttribute(
        'data-checkpoint',
        current ?? '',
    );

    await page.keyboard.press('Escape');
    await expect(audience).toHaveCount(0);
});

test('the workspace exports the selected presentation from the same revision', async ({ page }) => {
    await openWorkspace(page);
    const revision = await page.getByTestId('deck-revision').textContent();

    const offline = await page.request.get(`${server.base}/api/presentations/alpha/exports/offline-html`);
    expect(offline.status()).toBe(200);
    expect(offline.headers()['x-doxagon-revision']).toBe(revision);

    const archive = await page.request.get(`${server.base}/api/presentations/alpha/exports/source-archive`);
    expect(archive.status()).toBe(200);

    // Video stays explicitly deferred rather than silently producing a still.
    const video = await page.request.get(`${server.base}/api/presentations/alpha/exports/video`);
    expect(video.status()).toBe(501);
    expect((await video.json()).code).toBe('PRES_EXPORT_FORMAT_DEFERRED');
});

test('images are built from the workspace by the server\'s own capturer', async ({ page }) => {
    // A real capture launches a browser on the server and renders every Step,
    // so this test is given the budget that work honestly takes.
    test.slow();
    await openWorkspace(page);
    const revision = await page.getByTestId('deck-revision').textContent();

    // One control in the presentation toolbar, reachable and named in product
    // language. The click runs the hosted export: `POST /exports/raster` drives
    // the configured `PlaywrightRasterCapturer` over the closed offline
    // document and answers with the sealed archive.
    const control = page.getByTestId('export-raster');
    await expect(control).toBeEnabled();
    const [download] = await Promise.all([
        page.waitForEvent('download'),
        control.click(),
    ]);

    await expect(page.getByTestId('deck-notice')).toHaveText(`Images built from ${revision}`);
    expect(download.suggestedFilename()).toBe('alpha-images.zip');

    // The archive is the producer's: one PNG per Step in the workspace's own
    // order, and the export manifest that pins the revision, the verified
    // receipt, and the runtime signature each frame was captured at. The order
    // is read from the outline rather than assumed, because a Step this suite
    // moved earlier must move the frames with it.
    const order = await page.locator('.outline-select').evaluateAll(
        (nodes) => nodes.map((node) => (node as HTMLElement).dataset.checkpoint ?? ''),
    );
    const archive = readFileSync(await download.path());
    const manifest = JSON.parse(zipMember(archive, 'export-manifest.json').toString('utf-8'));
    expect(manifest.format).toBe('raster');
    expect(manifest.revision).toBe(revision);
    expect(manifest.receipt_sha256).toBeTruthy();
    expect(manifest.captures.map((capture: { checkpoint_id: string }) => capture.checkpoint_id)).toEqual(order);
    for (const [index, checkpoint] of order.entries()) {
        const frame = zipMember(archive, `${String(index).padStart(4, '0')}-${checkpoint}.png`);
        expect(frame.subarray(0, 4)).toEqual(Buffer.from('\x89PNG', 'binary'));
        // Only the runtime replaying that state can report its signature, so a
        // frame carrying one is a frame a browser really rendered.
        expect(manifest.signatures[checkpoint]).toBeTruthy();
        expect(frame.length).toBe(manifest.captures[index].bytes);
    }
});

test('no rendered panel names an internal contract outside a developer disclosure', async ({ page }) => {
    await openWorkspace(page);
    await expect(page.getByRole('tab')).toHaveText(TAB_LABELS);

    for (const label of TAB_LABELS.filter((label) => label !== 'Overview')) {
        await page.getByRole('tab', { name: label, exact: true }).click();
        const text = await page.evaluate(PRODUCT_TEXT) as string;
        for (const [word, pattern] of INTERNAL_VOCABULARY) {
            expect(text, `the ${label} panel says "${word}"`).not.toMatch(pattern);
        }
    }

    // The scan is only as honest as what it skips, so the two advanced regions
    // are checked to be exactly that: a disclosure that names the stable
    // identifier with its registered path, and the stored id `/groups/{id}`
    // addresses. Both are the producer's own vocabulary, shown verbatim.
    await outlineItem(page, FIRST).click();
    await page.getByRole('tab', { name: 'Source', exact: true }).click();
    await page.locator('[data-testid="source-technical"] summary').click();
    await expect(page.getByTestId('source-technical')).toContainText(FIRST);
    await expect(page.getByTestId('source-technical')).toContainText('Checkpoint ID');
    await expect(page.getByTestId('source-technical')).toContainText(`checkpoints/${FIRST}/document.html`);

    await page.getByRole('tab', { name: 'Sections', exact: true }).click();
    await expect(page.locator('[data-group="group-01-opening"] code[data-advanced="true"]'))
        .toHaveText('group-01-opening');
});

/** Select one synthetic project from the rail by its listed title. */
async function openProject(page: Page, name: RegExp) {
    await page.setViewportSize(DESKTOP);
    await useRealVault(page.context(), server);
    await page.goto('/presentations');
    await selectFromRail(page, name);
}

test('a refused migration lists every blocker the server published, by slide', async ({ page }) => {
    await openProject(page, /Blocked/);

    const panel = page.getByTestId('migration-blockers');
    await expect(panel).toBeVisible();

    // The producer's own refusal, read from the same backend the page read it
    // from. Every assertion below is measured against this payload rather than
    // against a list this test made up.
    const refusal = await (await page.request.get(`${server.base}/api/presentations/blocked`)).json();
    expect(refusal.code).toBe('PRES_MIGRATION_BLOCKED');
    expect(refusal.diagnostics.length).toBeGreaterThan(1);

    // One row per published diagnostic, in the producer's own order: nothing
    // is dropped and nothing is reduced to a count.
    const rows = panel.locator('li.blocker');
    await expect(rows).toHaveCount(refusal.diagnostics.length);
    const rendered = await rows.evaluateAll((nodes) =>
        nodes.map((node) => (node as HTMLElement).dataset.code ?? ''),
    );
    expect(rendered).toEqual(refusal.diagnostics.map((item: { code: string }) => item.code));

    // Grouped by the slide or file the producer located each finding against.
    const subjects = [
        ...new Set(refusal.diagnostics.map((item: { path: string }) => item.path.split('/')[0])),
    ];
    const grouped = await panel.locator('.blocker-subject').evaluateAll((nodes) =>
        nodes.map((node) => (node as HTMLElement).dataset.subject ?? ''),
    );
    expect(grouped).toEqual(subjects);
    await expect(panel.locator('[data-subject="02-stray"] li.blocker')).toHaveCount(2);
    await expect(panel.locator('[data-subject="04-html"]')).toContainText('Slide 04-html');

    // Plain product language leads each row; the internal code and the
    // producer's own sentence stay reachable as secondary detail.
    await expect(panel.locator('[data-subject="01-intro"] .blocker-summary')).toHaveText(
        'This slide offers more than one image and records no choice between them.',
    );
    const unsafe = panel.locator('[data-code="PRES_MIGRATION_HTML_UNSAFE"]');
    await expect(unsafe.locator('.blocker-summary')).toHaveText(
        'This slide\u2019s HTML runs script that cannot be carried across safely.',
    );
    await expect(unsafe.locator('code')).toHaveText('PRES_MIGRATION_HTML_UNSAFE');
    await expect(unsafe.locator('.blocker-location')).toHaveText('04-html/slide.html:3');

    // The bare refusal line this replaces is gone, and no internal contract
    // word reaches the primary copy.
    await expect(page.getByTestId('deck-failure')).toHaveCount(0);
    const text = await page.evaluate(PRODUCT_TEXT) as string;
    expect(text).not.toMatch(/mapping ambiguity/i);
    expect(text).not.toMatch(/PRES_MIGRATION/);
    for (const [word, pattern] of INTERNAL_VOCABULARY) {
        expect(text, `the blocker panel says "${word}"`).not.toMatch(pattern);
    }
});

test('a project with no presentation authored yet reads as a calm empty state', async ({ page }) => {
    await openProject(page, /Unwritten/);

    // The server's only blocker here is PRES_MIGRATION_EMPTY.
    const refusal = await (await page.request.get(`${server.base}/api/presentations/unwritten`)).json();
    expect(refusal.code).toBe('PRES_MIGRATION_EMPTY');
    expect(refusal.diagnostics).toEqual([]);

    await expect(page.getByTestId('presentation-empty')).toContainText('This project has no presentation yet');
    // Not a failure: no alert, no refusal code, no blocker list.
    await expect(page.getByTestId('deck-failure')).toHaveCount(0);
    await expect(page.getByTestId('migration-blockers')).toHaveCount(0);
    await expect(page.locator('.presentation-editor').getByRole('alert')).toHaveCount(0);
    const text = await page.evaluate(PRODUCT_TEXT) as string;
    expect(text).not.toMatch(/PRES_MIGRATION/);
    expect(text).not.toMatch(/did not complete/i);
});

test('/decks no longer competes with the presentation workspace', async ({ page }) => {
    await useRealVault(page.context(), server);
    await page.goto('/decks?thesis=alpha');

    await expect(page).toHaveURL(/\/presentations\?thesis=alpha/);
    await expect(page.locator('[data-presentation="alpha"]')).toHaveCount(1);
});

test('the desktop editor fits below the global header without a second viewport', async ({ page }) => {
    await openWorkspace(page);

    const overflow = await page.evaluate(() => ({
        documentScroll: document.documentElement.scrollHeight - document.documentElement.clientHeight,
        shell: document.querySelector('.workspace-shell')?.getBoundingClientRect().height ?? 0,
        viewport: window.innerHeight,
    }));
    expect(overflow.documentScroll).toBeLessThanOrEqual(1);
    expect(Math.round(overflow.shell)).toBeLessThanOrEqual(overflow.viewport);

    // The editor starts below the header and ends inside the viewport.
    const editor = await page.locator('.presentation-editor').boundingBox();
    const header = await page.locator('header').first().boundingBox();
    expect(editor!.y).toBeGreaterThanOrEqual((header?.y ?? 0));
    expect(editor!.y + editor!.height).toBeLessThanOrEqual(overflow.viewport + 1);

    mkdirSync(SCREENSHOTS, { recursive: true });
    await page.screenshot({ path: `${SCREENSHOTS}/presentation-workspace-desktop.png`, fullPage: false });
});

test('the mobile editor flows without overlap or clipped controls', async ({ page }) => {
    await openWorkspace(page, MOBILE);

    // One region at a time, so nothing paints over anything else.
    await page.getByRole('button', { name: 'Steps', exact: true }).click();
    const outline = await page.getByTestId('checkpoint-outline').boundingBox();
    expect(outline!.x).toBeGreaterThanOrEqual(0);
    expect(outline!.x + outline!.width).toBeLessThanOrEqual(MOBILE.width + 1);

    await page.getByRole('button', { name: 'Canvas', exact: true }).click();
    const realm = await page.locator('.presentation-editor .realm').boundingBox();
    // Width-derived height used to make the stage taller than the screen.
    expect(realm!.height).toBeLessThan(MOBILE.height);

    await page.getByRole('button', { name: 'Inspector', exact: true }).click();
    const tabs = page.getByRole('tab');
    await expect(tabs).toHaveCount(8);
    for (const name of ['Source', 'Transitions', 'Permissions', 'Sections', 'Media', 'Notes', 'Edit with AI']) {
        await expect(page.getByRole('tab', { name })).toBeVisible();
    }

    // No horizontal escape at any point in the flow.
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(MOBILE.width + 1);

    mkdirSync(SCREENSHOTS, { recursive: true });
    await page.screenshot({ path: `${SCREENSHOTS}/presentation-workspace-mobile.png`, fullPage: false });
});

test('the workspace keeps its keyboard, focus, and reduced-motion behaviour', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openWorkspace(page);

    await expect(page.getByTestId('preview-motion')).toHaveText('reduced');

    // Keyboard navigation drives the same session the buttons do. Focus stays
    // in the host document: a key pressed inside the opaque-origin realm never
    // reaches the host, which is exactly the isolation the sandbox buys.
    await page.locator('.chrome-title h2').click();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('preview-checkpoint')).toHaveText(SECOND);

    // The selected Step is announced, and every outline entry is reachable.
    await expect(outlineItem(page, SECOND)).toHaveAttribute('aria-current', 'true');
    await outlineItem(page, FIRST).focus();
    await expect(outlineItem(page, FIRST)).toBeFocused();
});

test('overview exposes every image and full-width source beneath the preview', async ({ page }) => {
    await openWorkspace(page);
    await expect(page.getByRole('tab', { name: 'Overview', exact: true })).toHaveAttribute('aria-selected', 'true');
    const images = page.locator('.overview-gallery img');
    await expect(images).toHaveCount(4);
    for (const image of await images.all()) {
        await image.scrollIntoViewIfNeeded();
        await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
    }
    await expect(page.locator('.overview-gallery')).toContainText('Unused candidate');
    await page.getByRole('tab', { name: 'Source', exact: true }).click();
    const stage = await page.locator('.stage').boundingBox();
    const inspector = await page.locator('.inspector').boundingBox();
    expect(inspector!.y).toBeGreaterThanOrEqual(stage!.y + stage!.height);
    const editor = await page.getByTestId('source-editor').boundingBox();
    expect(editor!.width).toBeGreaterThan(inspector!.width * 0.9);
    await page.getByRole('button', { name: 'CSS / imports', exact: true }).click();
    await expect(page.getByTestId('source-editor')).not.toHaveValue('');
});

test('gallery images open an in-app viewer that steps through every image', async ({ page, context }) => {
    await openWorkspace(page);
    const opened = context.pages().length;
    const images = page.locator('.overview-gallery img');
    await expect(images).toHaveCount(4);
    await page.locator('.overview-gallery .image-open').nth(1).click();

    const viewer = page.getByTestId('image-viewer');
    await expect(viewer).toBeVisible();
    expect(context.pages().length).toBe(opened);
    await expect(page.getByTestId('image-viewer-position')).toHaveText('2 of 4');
    const shown = page.getByTestId('image-viewer-image');
    await expect.poll(() => shown.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
    expect(await shown.getAttribute('alt')).toBe(await images.nth(1).getAttribute('alt'));

    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('image-viewer-position')).toHaveText('3 of 4');
    await page.getByRole('button', { name: 'Previous image' }).click();
    await page.getByRole('button', { name: 'Previous image' }).click();
    await expect(page.getByTestId('image-viewer-position')).toHaveText('1 of 4');
    await expect(viewer.getByRole('link', { name: 'Download original' })).toHaveAttribute('download', /.+/);

    await page.keyboard.press('Escape');
    await expect(viewer).toHaveCount(0);
    // The Media panel opens the same viewer from its own thumbnails.
    await page.getByRole('tab', { name: 'Media', exact: true }).click();
    await page.locator('.asset-grid .image-open').first().click();
    await expect(page.getByTestId('image-viewer-position')).toHaveText('1 of 4');
    await page.getByTestId('image-viewer-close').click();
    await expect(page.getByTestId('image-viewer')).toHaveCount(0);
});

test('presentation rail reveals on hover and focus, and compact steps can collapse', async ({ page }) => {
    await openWorkspace(page);
    const rail = page.getByRole('complementary', { name: 'Presentation projects' });
    const editor = page.locator('.workspace-content');
    const editorWidth = (await editor.boundingBox())!.width;
    // `openWorkspace` leaves the rail retracted, which is the resting state.
    expect((await rail.boundingBox())!.width).toBe(40);
    await rail.hover();
    await expect.poll(async () => (await rail.boundingBox())!.width).toBe(575);

    // The rail floats over the editor: revealing it must not reflow the canvas.
    expect((await editor.boundingBox())!.width).toBe(editorWidth);

    // Leaving the rail holds it open for a second, then retracts it over 750ms.
    // The poll waits for the end state rather than the clock.
    await page.mouse.move(1200, 400);
    await expect.poll(async () => (await rail.boundingBox())!.width, { timeout: 10_000 }).toBe(40);

    // Focus reveals it too, for a reader who never touches a pointer, and
    // releasing focus retracts it again.
    const railToggle = page.getByRole('button', { name: 'Toggle presentations sidebar' });
    await railToggle.focus();
    await expect.poll(async () => (await rail.boundingBox())!.width).toBe(575);
    await railToggle.blur();
    await expect.poll(async () => (await rail.boundingBox())!.width, { timeout: 10_000 }).toBe(40);

    await page.getByRole('button', { name: 'Collapse steps', exact: true }).click();
    await expect(page.getByTestId('checkpoint-outline')).toBeHidden();
    await page.getByRole('button', { name: 'Expand steps', exact: true }).click();
    await expect(page.getByTestId('checkpoint-outline')).toBeVisible();
    const row = await outlineItem(page, FIRST).boundingBox();
    expect(row!.height).toBeLessThanOrEqual(36);
    await expect(page.getByRole('button', { name: /^Move .+ (earlier|later)$/ })).toHaveCount(0);
});

/** Reveal the rail and return its filter, its groups, and its thesis buttons. */
async function openRail(page: Page) {
    await page.getByRole('complementary', { name: 'Presentation projects' }).hover();
    await expect(page.locator('.rail-group').first()).toBeVisible();
    return {
        filter: page.getByLabel('Filter presentations'),
        theses: page.locator('.thesis-select'),
        group: (slug: string) => page.locator(`.rail-group[data-diegesis="${slug}"]`),
    };
}

test('the rail nests every thesis under its diegesis and collapses one away', async ({ page }) => {
    await openWorkspace(page);
    const rail = await openRail(page);

    // Every scope the vault declares is listed, and `Alpha` is open, so the
    // rail opens showing only the theses of the scope holding the presentation
    // already on screen. A vault of any length is a list of scopes plus one.
    const listed = await (await page.request.get(`${server.base}/api/theses`)).json();
    const openScope = listed.filter((item: { diegesis: string }) => item.diegesis === 'synthetic');
    await expect(page.locator('.rail-group')).toHaveCount(2);
    await expect(rail.theses).toHaveCount(openScope.length);

    // `n-cartography` is in the library, so the group carries the title the
    // library gave it; `synthetic` is not, so that group keeps its slug.
    const cartography = rail.group('n-cartography');
    const scope = cartography.getByRole('button', { name: /^Cartography/ });
    await expect(rail.group('synthetic').getByRole('button', { name: /^synthetic/ })).toBeVisible();
    await expect(scope).toHaveAttribute('aria-expanded', 'false');

    // Opening the closed scope reveals the thesis it holds, and closing it
    // again takes that thesis away without touching any other scope.
    await scope.click();
    await expect(cartography.getByRole('button', { name: /Outline/ })).toBeVisible();
    await expect(rail.theses).toHaveCount(openScope.length + 1);
    await scope.click();
    await expect(cartography.getByRole('button', { name: /Outline/ })).toHaveCount(0);

    // One control reduces a whole vault to its scopes, and opens it again. The
    // label follows the rail: with a scope still open it offers to collapse.
    await page.getByRole('button', { name: 'Collapse all', exact: true }).click();
    await expect(rail.theses).toHaveCount(0);
    await page.getByRole('button', { name: 'Expand all', exact: true }).click();
    await expect(rail.theses).toHaveCount(listed.length);
});

test('a scope title too long for the rail stays on one truncated line', async ({ page }) => {
    await openWorkspace(page);
    const rail = await openRail(page);

    // A real vault names scopes in full sentences. Whatever a title's length,
    // a scope costs the rail exactly one row, so a collapsed rail is a
    // fixed-height list rather than a wall of wrapped headings.
    const rows = await page.locator('.diegesis-toggle').evaluateAll((nodes) =>
        nodes.map((node) => node.getBoundingClientRect().height),
    );
    expect(Math.max(...rows)).toBeLessThanOrEqual(40);

    const title = rail.group('n-cartography').locator('.diegesis-title');
    expect(await title.evaluate((node) => getComputedStyle(node).whiteSpace)).toBe('nowrap');
    expect(await title.evaluate((node) => getComputedStyle(node).textOverflow)).toBe('ellipsis');
});

test('the filter narrows the rail by thesis, by scope, and through a collapsed scope', async ({ page }) => {
    await openWorkspace(page);
    const rail = await openRail(page);

    await rail.filter.fill('numbered');
    await expect(rail.theses).toHaveText([/Numbered/]);

    // Naming a scope keeps every thesis inside it, so the filter reaches the
    // grouping as well as the titles.
    await rail.filter.fill('cartography');
    await expect(rail.theses).toHaveText([/Outline/]);

    // A hit is shown wherever it lives. Cleared, this scope is collapsed —
    // and the filter still finds and opens the thesis inside it.
    await rail.filter.fill('');
    await expect(rail.group('n-cartography').getByRole('button', { name: /^Cartography/ }))
        .toHaveAttribute('aria-expanded', 'false');
    await rail.filter.fill('outline');
    await rail.theses.click();
    await expect(page.getByTestId('checkpoint-outline').locator('li')).toHaveCount(5);

    await rail.filter.fill('no thesis carries this');
    await expect(rail.theses).toHaveCount(0);
    await expect(page.getByText(/No thesis matches/)).toBeVisible();
});
