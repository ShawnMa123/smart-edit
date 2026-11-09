/**
 * Document snapshots and their content digest (design D2).
 *
 * The digest is computed **in this browser** over the UTF-8 bytes of the exact text. It identifies
 * which text was sent to the audit; it is not tamper-evident and it is not the server-side
 * deterministic digest VER-03 requires (the UI says so).
 */

export interface Snapshot {
  text: string;
  digest: string;
  versionId: string | null;
  capturedAt: string;
}

const toHex = (buffer: ArrayBuffer): string =>
  Array.from(new Uint8Array(buffer))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');

/** SHA-256 of `text` encoded as UTF-8, lowercase hex. */
export async function digestText(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const hash = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return toHex(hash);
}

/** Freeze the current editor text into an immutable snapshot. */
export async function createSnapshot(
  text: string,
  versionId: string | null = null,
  now: Date = new Date(),
): Promise<Snapshot> {
  return {
    text,
    digest: await digestText(text),
    versionId,
    capturedAt: now.toISOString(),
  };
}

/** Short form for display; the full digest stays available on the snapshot. */
export const shortDigest = (digest: string): string => digest.slice(0, 12);