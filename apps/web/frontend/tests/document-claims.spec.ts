import { expect, test } from '@playwright/test';
import { parseDocumentReady } from '../src/lib/presentation/documentBridge';
import { claimHref, claimLabel } from '../src/lib/presentation/claimLabels';

const ready = (cue: Record<string, unknown>) => ({
    type: 'ready',
    documentId: 'synthetic-telling',
    edition: '2026-telling',
    cues: [{ id: 'airlock', title: 'The airlock', ...cue }],
});

test('a cue without claims parses as it did before tellings', () => {
    expect(parseDocumentReady(ready({}))?.cues[0]).toEqual({ id: 'airlock', title: 'The airlock' });
});

test('a cue keeps the claims it declares', () => {
    expect(parseDocumentReady(ready({ claims: ['d-partisan-validators', 'd-household-verification-airlock'] }))?.cues[0].claims)
        .toEqual(['d-partisan-validators', 'd-household-verification-airlock']);
});

test('a malformed claim id refuses the whole ready message', () => {
    expect(parseDocumentReady(ready({ claims: ['not-a-doxa'] }))).toBeNull();
});

test('a repeated claim id refuses the whole ready message', () => {
    expect(parseDocumentReady(ready({ claims: ['d-partisan-validators', 'd-partisan-validators'] }))).toBeNull();
});

test('a claims field that is not an array of strings refuses the ready message', () => {
    expect(parseDocumentReady(ready({ claims: 'd-partisan-validators' }))).toBeNull();
});

const manyClaims = (count: number) => Array.from({ length: count }, (_, index) => `d-claim-${index}`);

test('a cue keeps the largest claim list the bridge admits', () => {
    expect(parseDocumentReady(ready({ claims: manyClaims(32) }))?.cues[0].claims).toEqual(manyClaims(32));
});

test('one claim beyond the cap refuses the whole ready message', () => {
    expect(parseDocumentReady(ready({ claims: manyClaims(33) }))).toBeNull();
});

test('an authored short label is the chip text', () => {
    expect(claimLabel('d-partisan-validators', 'Validators serve their master', 'Validators are partisan: they read every ambiguity in favour of whoever appointed them'))
        .toBe('Validators serve their master');
});

test('a belief without a short label is cut at a word boundary', () => {
    expect(claimLabel('d-household-verification-airlock', null, 'Households verify high-risk actions in an airlock before they reach the world'))
        .toBe('Households verify high-risk…');
});

test('a belief whose first word overruns the budget keeps that word whole', () => {
    expect(claimLabel('d-counterdisintermediation', null, 'Counterdisintermediationalisation defeats the household airlock'))
        .toBe('Counterdisintermediationalisation…');
});

test('a belief that is one long word with nothing elided drops the ellipsis', () => {
    expect(claimLabel('d-counterdisintermediation', null, 'Counterdisintermediationalisation')).toBe('Counterdisintermediationalisation');
});

test('a chip points at the graph view of its doxa', () => {
    expect(claimHref('d-partisan-validators')).toBe('/?node=d-partisan-validators');
});
