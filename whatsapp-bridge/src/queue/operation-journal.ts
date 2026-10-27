import { createHash, randomUUID } from "node:crypto";
import { link, mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import path from "node:path";
import { BridgeError, outcomeUnknown } from "../domain/errors.js";

export const digest = (value: string | Buffer): string => createHash("sha256").update(value).digest("hex");

export interface OperationBinding { fingerprint: string; account: string }
interface RecordData extends OperationBinding {
  version: 1;
  state: "pending" | "completed";
  message_id?: string;
}

export interface Journal {
  lookup(operationId: string, binding: OperationBinding): Promise<string | null>;
  reserve(operationId: string, binding: OperationBinding): Promise<string | null>;
  complete(operationId: string, binding: OperationBinding, messageId: string): Promise<void>;
}

function filesystemCode(error: unknown): string | undefined {
  return (error as NodeJS.ErrnoException)?.code;
}

function journalError(): BridgeError {
  return new BridgeError(503, "journal_unavailable", "The operation journal is unavailable", false);
}

/** Contains only hashes and receipts. Pending records are deliberately never
 * replayed or removed. Keep this directory across restarts and deployments. */
export class OperationJournal implements Journal {
  private readonly directory: string;
  constructor(runtimeDir: string) { this.directory = path.join(runtimeDir, "operations-v1"); }

  private file(operationId: string): string { return path.join(this.directory, `${digest(operationId)}.json`); }

  async lookup(operationId: string, binding: OperationBinding): Promise<string | null> {
    let record: RecordData;
    try {
      const content = await readFile(this.file(operationId), "utf8");
      if (content.length > 4096) throw new Error();
      record = JSON.parse(content) as RecordData;
      if (record.version !== 1 || !["pending", "completed"].includes(record.state) || typeof record.account !== "string" || typeof record.fingerprint !== "string") throw new Error();
    } catch (error) {
      if (filesystemCode(error) === "ENOENT") return null;
      throw journalError();
    }
    if (record.fingerprint !== binding.fingerprint || record.account !== binding.account) {
      throw new BridgeError(409, "operation_conflict", "The operation ID belongs to a different request or account", false);
    }
    if (record.state === "pending") throw outcomeUnknown();
    if (typeof record.message_id !== "string" || !record.message_id.trim() || record.message_id.length > 512) throw journalError();
    return record.message_id;
  }

  private async write(operationId: string, record: RecordData, exclusive: boolean): Promise<void> {
    let temporary: string | undefined;
    try {
      await mkdir(this.directory, { recursive: true, mode: 0o700 });
      temporary = path.join(this.directory, `${digest(operationId)}.${randomUUID()}.tmp`);
      const file = await open(temporary, "wx", 0o600);
      try { await file.writeFile(JSON.stringify(record)); await file.sync(); }
      finally { await file.close(); }
      // Hard-link publication is atomic AND exclusive, including across processes.
      // A crash before publication cannot have submitted an external send.
      if (exclusive) await link(temporary, this.file(operationId));
      else await rename(temporary, this.file(operationId));
      // Persist directory entries where supported. Windows does not expose fsync
      // for directory handles; durability there depends on the local filesystem.
      if (process.platform !== "win32") {
        const directory = await open(this.directory, "r");
        try { await directory.sync(); } finally { await directory.close(); }
      }
    } finally {
      if (temporary) await unlink(temporary).catch(() => undefined);
    }
  }

  async reserve(operationId: string, binding: OperationBinding): Promise<string | null> {
    try { await this.write(operationId, { version: 1, ...binding, state: "pending" }, true); }
    catch (error) {
      if (filesystemCode(error) === "EEXIST") {
        const completed = await this.lookup(operationId, binding);
        if (completed) return completed;
        // A pending operation may never be submitted again, even if the race
        // was observed from another process.
        throw outcomeUnknown();
      }
      throw journalError();
    }
    return null;
  }

  async complete(operationId: string, binding: OperationBinding, messageId: string): Promise<void> {
    try { await this.write(operationId, { version: 1, ...binding, state: "completed", message_id: messageId }, false); }
    catch { throw outcomeUnknown(); }
  }
}
