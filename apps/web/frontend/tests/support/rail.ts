import { expect, type Page } from '@playwright/test';

/** The rail's resting width where it is an overlay. */
const CLOSED = 40;

/** Below this the rail is a stacked band, not a hovering overlay. */
const OVERLAY_FROM = 1024;

/**
 * Open one presentation from the project rail, and leave the rail closed.
 *
 * The rail nests every thesis under its diegesis and opens with those scopes
 * collapsed, so reaching a thesis means naming it: the filter shows every hit
 * wherever it lives, which is the same path a reader takes through a vault too
 * long to scan.
 *
 * Retracting afterwards is part of selecting, not tidiness. The open rail is an
 * overlay that covers the left of the editor, and it stays open while the
 * pointer is over it or focus is inside it — so a caller that went straight on
 * to click the canvas would be clicking underneath the rail. Leaving the rail
 * closed hands back the state a reader actually works in.
 */
export async function selectFromRail(page: Page, name: RegExp | string): Promise<void> {
    const rail = page.getByRole('complementary', { name: 'Presentation projects' });
    await rail.hover();

    const filter = page.getByLabel('Filter presentations');
    await filter.fill(typeof name === 'string' ? name : name.source.replace(/[^\w\s-]/g, ''));
    const wanted = page.locator('.thesis-select').filter({ hasText: name });
    await expect(wanted).toHaveCount(1);
    await wanted.click();

    // A filter left in the box keeps narrowing the rail, and focus left in it
    // keeps the rail open, so both are released before standing back.
    await filter.fill('');
    await filter.blur();

    // Only the overlay retracts. On a narrow viewport the rail is a band above
    // the editor that covers nothing, so there is nothing to wait for.
    if ((page.viewportSize()?.width ?? OVERLAY_FROM) < OVERLAY_FROM) return;
    await page.mouse.move(1200, 400);
    // A second of grace, then 750ms of travel. The poll waits for the end state
    // rather than the clock.
    await expect.poll(async () => (await rail.boundingBox())!.width, { timeout: 10_000 }).toBe(CLOSED);
}
