/**
 * The presenter's script: one slide's notes as an ordered column of passages.
 *
 * Notes are authored per Step, because a Step is the moment the presenter
 * says the next thing. Read back, they are one continuous script for the
 * slide, so the presenter sees the whole slide's notes with the current Step's
 * passage emphasized and the next one already in view.
 */

import type { SlideRun } from './deck';

export interface ScriptPassage {
    /** The Step this passage is spoken on. */
    checkpointId: string;
    /** The cue within that Step, for a document whose interior is authored. */
    cue?: string;
    text: string;
}

/**
 * One document's script: a passage per cue, in the order the cues are declared.
 *
 * A document is one Step but many moments, so its notes are authored per cue.
 * Read back they are one continuous script, exactly as a slide's Steps are.
 */
export function documentScript(checkpointId: string, cues: string[], notes: Record<string, string>): ScriptPassage[] {
    const passages: ScriptPassage[] = [];
    for (const cue of cues) {
        const text = (notes[cue] ?? '').trim();
        if (text === '') continue;
        passages.push({ checkpointId, cue, text });
    }
    return passages;
}

/** Which passage the presenter is reading at `cue`, or the most recent one. */
export function currentCuePassage(passages: ScriptPassage[], cues: string[], cue: string | null): number {
    if (cue === null || passages.length === 0) return -1;
    const position = cues.indexOf(cue);
    if (position < 0) return -1;
    let current = -1;
    for (let index = 0; index < passages.length; index += 1) {
        if (cues.indexOf(passages[index].cue ?? '') <= position) current = index;
        else break;
    }
    return current;
}

/**
 * The passages of the slide run holding `checkpointId`, in playback order.
 *
 * Steps with no notes contribute no passage. Consecutive Steps that carry
 * byte-identical notes contribute one: a slide whose notes were copied onto
 * every reveal Step reads once, not once per reveal, and the copy is credited
 * to the first Step so the emphasis lands where the words are first spoken.
 */
export function slideScript(
    run: SlideRun | null,
    notesFor: (checkpointId: string) => string | null | undefined,
): ScriptPassage[] {
    if (run === null) return [];
    const passages: ScriptPassage[] = [];
    for (const step of run.steps) {
        const text = (notesFor(step.id) ?? '').trim();
        if (text === '') continue;
        const previous = passages[passages.length - 1];
        if (previous !== undefined && previous.text === text) continue;
        passages.push({ checkpointId: step.id, text });
    }
    return passages;
}

/**
 * Which passage the presenter is reading on `checkpointId`.
 *
 * A Step whose own notes were folded into an earlier identical passage, or
 * that has no notes at all, keeps the most recent passage emphasized: the
 * presenter is still inside those words, not between passages.
 */
export function currentPassage(passages: ScriptPassage[], run: SlideRun | null, checkpointId: string | null): number {
    if (run === null || checkpointId === null || passages.length === 0) return -1;
    const order = run.steps.map((step) => step.id);
    const position = order.indexOf(checkpointId);
    if (position < 0) return -1;
    let current = -1;
    for (let index = 0; index < passages.length; index += 1) {
        if (order.indexOf(passages[index].checkpointId) <= position) current = index;
        else break;
    }
    return current;
}
