import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { DeckRuntime } from '../src/lib/presentation/runtime';

/**
 * Browser proof for the one checkpoint runtime.
 *
 * The artifact under test is the committed offline export in
 * `tests/fixtures/presentations/synthetic-deck.offline.html`, produced by
 * `doxagon.presentations.exporters.export_offline_html` from the synthetic
 * fixture deck. `tests/test_presentations_runtime.py` fails if that file stops
 * matching the current runtime, so this suite can never drift into proving an
 * old build.
 */

const OFFLINE = fileURLToPath(new URL('../../../../tests/fixtures/presentations/synthetic-deck.offline.html', import.meta.url));
const document = readFileSync(OFFLINE, 'utf8');

type DeckState = { checkpointId: string | null; signature: string | null; sequence: number };

declare global {
    interface Window {
        doxagonDeck: {
            revision: string;
            runtimeVersion: string;
            seek(id: string): Promise<DeckState>;
            dispatch(action: { type: string; checkpointId?: string }): Promise<DeckState>;
            state(): DeckState;
            signatures(): Record<string, string>;
            scroll(): Promise<{ scrollTop: number; scrollHeight: number; clientHeight: number } | null>;
            runtime: DeckRuntime;
        };
    }
}

async function offlineDeck(page: Page) {
    await page.setContent(document, { waitUntil: 'load' });
    await expect.poll(
        () => page.evaluate(() => window.document.documentElement.dataset.doxagonReady),
        { timeout: 15000 },
    ).toBe('true');
}

test('a closed export loads and reaches its first checkpoint with no network at all', async ({ page }) => {
    const requested: string[] = [];
    page.on('request', (request) => requested.push(request.url()));
    await offlineDeck(page);

    expect(requested).toEqual([]);
    const state = await page.evaluate(() => window.doxagonDeck.state());
    expect(state.checkpointId).toBe('market-base');
    expect(state.signature).toBe('market-base:asset-market-map');
});

test('seeking the same checkpoint twice rebuilds it from source to the same signature', async ({ page }) => {
    await offlineDeck(page);

    const first = await page.evaluate(() => window.doxagonDeck.seek('market-forecast'));
    await page.evaluate(() => window.doxagonDeck.seek('market-base'));
    const second = await page.evaluate(() => window.doxagonDeck.seek('market-forecast'));

    expect(second.signature).toBe(first.signature);
    // A fresh realm each time: the sequence advances, the state does not.
    expect(second.sequence).toBeGreaterThan(first.sequence);
    expect(await page.evaluate(() => window.doxagonDeck.runtime.inspect())).toMatchObject({ drawn: '5' });
});

test('a realm is destroyed on the way out so only one checkpoint is ever mounted', async ({ page }) => {
    await offlineDeck(page);
    await page.evaluate(() => window.doxagonDeck.seek('market-forecast'));
    await expect(page.locator('#doxagon-stage iframe')).toHaveCount(1);
    await page.evaluate(() => window.doxagonDeck.seek('probe-denied'));
    await expect(page.locator('#doxagon-stage iframe')).toHaveCount(1);
});

test('Next and Back traverse the registered edge in both directions', async ({ page }) => {
    await offlineDeck(page);

    expect((await page.evaluate(() => window.doxagonDeck.dispatch({ type: 'NEXT' }))).checkpointId).toBe('market-forecast');
    expect((await page.evaluate(() => window.doxagonDeck.dispatch({ type: 'PREVIOUS' }))).checkpointId).toBe('market-base');
    expect((await page.evaluate(() => window.doxagonDeck.dispatch({ type: 'HOME' }))).checkpointId).toBe('market-base');
    // END lands on the deliberately leaky checkpoint, which cannot be left; the
    // leak itself is proved below rather than smuggled into this traversal.
    expect((await page.evaluate(() => window.doxagonDeck.dispatch({ type: 'END' }))).checkpointId).toBe('leaky-timer');
});

test('keyboard controls drive the same absolute seek as the buttons', async ({ page }) => {
    await offlineDeck(page);

    await page.keyboard.press('ArrowRight');
    await expect.poll(() => page.evaluate(() => window.doxagonDeck.state().checkpointId)).toBe('market-forecast');
    await page.keyboard.press('ArrowLeft');
    await expect.poll(() => page.evaluate(() => window.doxagonDeck.state().checkpointId)).toBe('market-base');

    await page.getByRole('button', { name: 'Last checkpoint' }).click();
    await expect.poll(() => page.evaluate(() => window.doxagonDeck.state().checkpointId)).toBe('leaky-timer');
});

test('an ungranted host API is refused inside the realm even when the scanner never saw it', async ({ page }) => {
    await offlineDeck(page);
    await page.evaluate(() => window.doxagonDeck.seek('probe-denied'));

    const probe = await page.evaluate(() => window.doxagonDeck.runtime.inspect());
    // The checkpoint assembles these names at run time, so no static rule
    // flagged them: this is the runtime broker refusing, not the validator.
    expect(probe?.network).toContain('PRES_CAPABILITY_DENIED');
    expect(probe?.storage).toContain('PRES_CAPABILITY_DENIED');
    expect(probe?.worker).toContain('PRES_CAPABILITY_DENIED');
});

test('a granted capability is reachable only through the broker, never the raw host API', async ({ page }) => {
    await offlineDeck(page);
    // `probe-denied` IS granted `timers`, and assembles `setTimeout` at run
    // time so no static rule sees it.
    await page.evaluate(() => window.doxagonDeck.seek('probe-denied'));

    const probe = await page.evaluate(() => window.doxagonDeck.runtime.inspect());
    // A grant used to skip withdrawal entirely, leaving the raw global — and
    // therefore an untracked handle — reachable beside the broker.
    expect(probe?.['timers-raw']).toContain('PRES_CAPABILITY_UNBROKERED');
    // The brokered form works and its handle is accounted for and closable.
    expect(probe?.['timers-brokered']).toBe('handle');
    expect(probe?.['timers-open']).toBe('timers');
    expect(probe?.['timers-closed']).toBe('closed');
});

test('broker internals are not lexically reachable from author code', async ({ page }) => {
    await offlineDeck(page);
    await page.evaluate(() => window.doxagonDeck.seek('probe-denied'));
    const probe = await page.evaluate(() => window.doxagonDeck.runtime.inspect());

    // The broker program and the author entry used to be concatenated into one
    // ES module, so these names resolved for arbitrary author code: the raw
    // host APIs, the open-handle registry, and the host reference were all in
    // scope. They are separate module scripts now.
    expect(probe?.['broker-raw']).toBe('unreachable');
    expect(probe?.['broker-open']).toBe('unreachable');
    expect(probe?.['broker-host']).toBe('unreachable');
    expect(probe?.['broker-broker']).toBe('unreachable');
    // The one global the broker exposes is the registrar, and it is withdrawn
    // once the realm's scripts have run.
    expect(probe?.['broker-registrar']).toBe('undefined');
});

test('a reply forged by a checkpoint settles nothing the host asked for', async ({ page }) => {
    await offlineDeck(page);
    // `probe-denied` posts forged {id, ok, signature} answers to the host while
    // it enters, covering the ids the host's own requests use.
    const state = await page.evaluate(() => window.doxagonDeck.seek('probe-denied'));
    const probe = await page.evaluate(() => window.doxagonDeck.runtime.inspect());

    expect(probe?.['reply-forgery']).toBe('sent');
    // Host traffic runs over a private MessagePort the checkpoint has no
    // reference to, so the state the host reports is the one the checkpoint's
    // own signature() computed — never the forged string it posted.
    expect(state.signature).not.toBe('forged-signature');
    expect(state.signature).toContain('probe-denied:');
    expect(await page.evaluate(() => window.doxagonDeck.state().signature)).toBe(state.signature);
    // The realm still answers the host afterwards: the forgery was ignored, not
    // fatal to the channel.
    expect((await page.evaluate(() => window.doxagonDeck.seek('market-base'))).checkpointId).toBe('market-base');
});

test('a checkpoint realm cannot read the host document', async ({ page }) => {
    await offlineDeck(page);
    await page.evaluate(() => window.doxagonDeck.seek('probe-denied'));
    expect((await page.evaluate(() => window.doxagonDeck.runtime.inspect()))?.['cross-realm']).toBe('refused');
});

test('leaving a checkpoint that leaks a brokered handle fails the transition', async ({ page }) => {
    await offlineDeck(page);
    await page.evaluate(() => window.doxagonDeck.seek('leaky-timer'));

    const failure = await page.evaluate(async () => {
        try {
            await window.doxagonDeck.seek('market-base');
            return { code: 'none' };
        } catch (error) {
            return { code: (error as { code: string }).code, message: (error as Error).message };
        }
    });
    expect(failure.code).toBe('PRES_CHECKPOINT_LEAK');
    expect(failure.message).toContain('leaky-timer');
});

test('the shell reports its revision and the runtime that produced it', async ({ page }) => {
    await offlineDeck(page);
    const meta = await page.evaluate(() => ({
        revision: window.document.querySelector('meta[name="doxagon-revision"]')?.getAttribute('content'),
        runtime: window.document.querySelector('meta[name="doxagon-runtime"]')?.getAttribute('content'),
        deckRevision: window.doxagonDeck.revision,
        deckRuntime: window.doxagonDeck.runtimeVersion,
    }));

    expect(meta.revision).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(meta.deckRevision).toBe(meta.revision);
    expect(meta.deckRuntime).toBe(meta.runtime);
});

test('an overflowing checkpoint scrolls inside its own realm', async ({ page }) => {
    await page.setViewportSize({ width: 480, height: 320 });
    await offlineDeck(page);

    const scroll = await page.evaluate(() => window.doxagonDeck.scroll());
    expect(scroll).not.toBeNull();
    // Parity: the realm owns the overflow, so the host page never grows a
    // second scrollbar around a checkpoint.
    expect(await page.evaluate(() => window.document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
