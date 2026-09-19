import { sha256 } from '@noble/hashes/sha2.js';

export async function documentDigest(content: ArrayBuffer): Promise<string> {
    // Plain HTTP LAN origins have no SubtleCrypto. Keep the same byte-identity
    // check there instead of requiring HTTPS or skipping verification.
    const subtle = globalThis.crypto?.subtle;
    const digest = subtle
        ? new Uint8Array(await subtle.digest('SHA-256', content))
        : sha256(new Uint8Array(content));
    return Array.from(digest, value => value.toString(16).padStart(2, '0')).join('');
}
