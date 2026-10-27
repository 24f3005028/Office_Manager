import path from "node:path";
import type { BridgeConfig } from "../config.js";
import type { WhatsappClient } from "../client/whatsapp-client.js";
import { BridgeError } from "../domain/errors.js";
import { bounded, systemClock, type Clock } from "../domain/clock.js";
import { readPdf, validateUploadedPdf } from "../domain/path-validation.js";
import type { SendReceipt } from "../domain/types.js";
import { digest, OperationJournal, type Journal } from "./operation-journal.js";
import { SendQueue } from "./send-queue.js";

interface BaseCommand { operationId: string; contactId: string; generation?: number }
export type SendCommand = BaseCommand & (
  | { kind: "text"; text: string }
  | { kind: "path"; filePath: string; caption?: string }
  | { kind: "upload"; buffer: Buffer; filename: string; caption?: string }
);

export class OperationSender {
  private readonly inFlight = new Map<string, { binding: string; promise: Promise<SendReceipt> }>();
  private closed = false;
  private readonly cancelLookups = new Set<() => void>();

  constructor(
    private readonly config: BridgeConfig,
    private readonly whatsapp: WhatsappClient,
    private readonly queue = new SendQueue(config.sendDelayMs, config.sendCapacity, config.sendDeadlineMs),
    private readonly journal: Journal = new OperationJournal(config.runtimeDir),
    private readonly clock: Clock = systemClock,
  ) {}

  async send(command: SendCommand): Promise<SendReceipt> {
    if (this.closed) throw new BridgeError(503, "shutting_down", "The bridge is shutting down", true);
    const snapshot = this.whatsapp.snapshot(command.generation);
    const request = command.kind === "text" ? ["text", command.contactId, command.text]
      : command.kind === "path" ? ["path", command.contactId, path.resolve(command.filePath), command.caption ?? ""]
      : ["upload", command.contactId, command.filename, digest(command.buffer), command.caption ?? ""];
    const binding = { fingerprint: digest(JSON.stringify(request)), account: digest(`office-dashboard:${snapshot.account}`) };
    const bindingKey = JSON.stringify(binding);
    const active = this.inFlight.get(command.operationId);
    if (active) {
      if (active.binding !== bindingKey) throw new BridgeError(409, "operation_conflict", "The operation ID belongs to a different request or account");
      return active.promise;
    }
    if (this.inFlight.size >= this.config.sendCapacity) throw new BridgeError(503, "queue_full", "The send queue is full", true);
    const receipt = (messageId: string): SendReceipt => ({ status: "sent", message_id: messageId, operation_id: command.operationId });
    const deadline = this.clock.now() + this.config.sendDeadlineMs;
    const promise = (async () => {
      let cancel!: () => void;
      const stopped = new Promise<never>((_resolve, reject) => {
        cancel = () => reject(new BridgeError(503, "shutting_down", "The bridge is shutting down", true));
        this.cancelLookups.add(cancel);
      });
      let completed: string | null;
      try {
        completed = await bounded(Promise.race([this.journal.lookup(command.operationId, binding), stopped]), this.config.sendDeadlineMs, this.clock);
      } catch (error) {
        if (error instanceof BridgeError) throw error;
        throw new BridgeError(503, "journal_unavailable", "The operation journal is unavailable", false);
      } finally { this.cancelLookups.delete(cancel); }
      this.whatsapp.assertSnapshot(snapshot);
      if (completed) return receipt(completed);
      if (this.closed) throw new BridgeError(503, "shutting_down", "The bridge is shutting down", true);
      return this.queue.enqueue(async (context) => {
        this.whatsapp.assertSnapshot(snapshot);
        context.assertActive();
        let document: { buffer: Buffer; filename: string } | undefined;
        if (command.kind === "path") {
          document = await readPdf(command.filePath, () => this.config.allowedRoots, this.config.fileReadTimeoutMs, context.signal, this.clock);
        } else if (command.kind === "upload") {
          validateUploadedPdf(command.filename, command.buffer);
          document = command;
        }
        this.whatsapp.assertSnapshot(snapshot);
        context.assertActive();
        // Resolve LIDs before reserving. An invalid/unresolved recipient is a
        // not-started request and must not leave a restart-time unknown record.
        await this.whatsapp.resolveRecipient(snapshot, command.contactId);
        context.assertActive();
        // The durable pending record MUST precede the first possible SDK call.
        const existingReceipt = await this.journal.reserve(command.operationId, binding);
        if (existingReceipt) return receipt(existingReceipt);
        this.whatsapp.assertSnapshot(snapshot);
        context.assertActive();
        const id = command.kind === "text"
          ? await this.whatsapp.sendText(snapshot, command.contactId, command.text, context)
          : await this.whatsapp.sendBuffer(snapshot, command.contactId, document!.buffer, document!.filename, command.caption, context);
        this.whatsapp.assertSnapshot(snapshot);
        context.assertActive();
        await this.journal.complete(command.operationId, binding, id);
        this.whatsapp.assertSnapshot(snapshot);
        context.assertActive();
        return receipt(id);
      }, Math.max(1, deadline - this.clock.now()));
    })();
    this.inFlight.set(command.operationId, { binding: bindingKey, promise });
    void promise.finally(() => {
      if (this.inFlight.get(command.operationId)?.promise === promise) this.inFlight.delete(command.operationId);
    }).catch(() => undefined);
    return promise;
  }

  close(): void {
    this.closed = true;
    for (const cancel of this.cancelLookups) cancel();
    this.cancelLookups.clear();
    this.queue.close();
  }
}
