import path from "node:path";
import { open, realpath, stat } from "node:fs/promises";
import { BridgeError } from "./errors.js";
import { bounded, systemClock, type Clock } from "./clock.js";

export const MAX_PDF_BYTES = 25 * 1024 * 1024;

export class PathValidationError extends BridgeError {
  constructor() { super(400, "invalid_pdf", "The PDF is invalid or outside the allowed document roots"); }
}

export function isWithinAllowedRoot(candidate: string, root: string): boolean {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative.length > 0 && !relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative);
}

export async function validateAllowedRoots(value: unknown): Promise<string[]> {
  if (!Array.isArray(value) || value.length > 100 || value.some((root) => typeof root !== "string" || !root.trim() || !path.isAbsolute(root))) {
    throw new BridgeError(400, "invalid_roots", "Roots must be an array of absolute directory paths");
  }
  try {
    const roots = await Promise.all(value.map(async (root: string) => {
      const resolved = await realpath(root);
      if (!(await stat(resolved)).isDirectory()) throw new Error();
      return resolved;
    }));
    return [...new Set(roots)];
  } catch {
    throw new BridgeError(400, "invalid_roots", "Every allowed root must be an accessible directory");
  }
}

export async function validatePdfPath(filePath: string, allowedRoots: readonly string[]): Promise<string> {
  if (!filePath.trim() || !allowedRoots.length || path.extname(filePath).toLowerCase() !== ".pdf") throw new PathValidationError();
  try {
    const candidate = await realpath(filePath);
    const info = await stat(candidate);
    if (!info.isFile() || info.size < 5 || info.size > MAX_PDF_BYTES) throw new PathValidationError();
    const roots = await Promise.all(allowedRoots.map((root) => realpath(root).catch(() => null)));
    if (!roots.some((root) => root !== null && isWithinAllowedRoot(candidate, root))) throw new PathValidationError();
    return candidate;
  } catch { throw new PathValidationError(); }
}

export function validateUploadedPdf(filename: string, buffer: Buffer): void {
  if (!filename.trim() || path.extname(filename).toLowerCase() !== ".pdf" || buffer.length < 5 || buffer.length > MAX_PDF_BYTES || buffer.subarray(0, 5).toString("ascii") !== "%PDF-") {
    throw new PathValidationError();
  }
}

/** Called at execution, with the current roots. Bounded reads + handle metadata
 * revalidation narrow replacement races; they cannot eliminate all filesystem races. */
export async function readPdf(
  filePath: string, roots: () => readonly string[], timeoutMs: number,
  signal?: AbortSignal, clock: Clock = systemClock,
): Promise<{ buffer: Buffer; filename: string }> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) cancel();
  const check = () => { if (controller.signal.aborted) throw new PathValidationError(); };
  const work = (async () => {
    let handle: Awaited<ReturnType<typeof open>> | undefined;
    try {
      check();
      const candidate = await validatePdfPath(filePath, roots());
      check();
      handle = await open(candidate, "r");
      const before = await handle.stat();
      if (!before.isFile() || before.size < 5 || before.size > MAX_PDF_BYTES) throw new PathValidationError();
      const buffer = Buffer.alloc(before.size);
      let offset = 0;
      while (offset < buffer.length) {
        check();
        const { bytesRead } = await handle.read(buffer, offset, Math.min(64 * 1024, buffer.length - offset), offset);
        if (!bytesRead) throw new PathValidationError();
        offset += bytesRead;
      }
      const after = await handle.stat();
      const current = await stat(await validatePdfPath(filePath, roots()));
      if (before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs || current.dev !== after.dev || current.ino !== after.ino || current.size !== after.size || current.mtimeMs !== after.mtimeMs) throw new PathValidationError();
      check();
      const filename = path.basename(candidate);
      validateUploadedPdf(filename, buffer);
      return { buffer, filename };
    } catch { throw new PathValidationError(); }
    finally { await handle?.close().catch(() => undefined); }
  })();
  try { return await bounded(work, timeoutMs, clock); }
  catch { throw new PathValidationError(); }
  finally { cancel(); signal?.removeEventListener("abort", cancel); }
}
