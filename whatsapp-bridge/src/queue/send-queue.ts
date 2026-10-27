import { systemClock, type Clock } from "../domain/clock.js";
import { BridgeError, outcomeUnknown } from "../domain/errors.js";

export interface SendContext {
  readonly signal: AbortSignal;
  readonly submitted: boolean;
  assertActive(): void;
  markSubmitted(): void;
}

interface Entry {
  run(context: SendContext): Promise<unknown>;
  resolve(value: unknown): void;
  reject(error: unknown): void;
  controller: AbortController;
  submitted: boolean;
  replied: boolean;
  timer?: unknown;
}

/** One scheduler. A deadline ends the HTTP wait, not the underlying SDK call.
 * Its lane remains occupied until that call really settles (fail closed). */
export class SendQueue {
  private readonly waiting: Entry[] = [];
  private active: Entry | null = null;
  private closed = false;
  private cooldownUntil = 0;
  private cooldownTimer?: unknown;

  constructor(
    private readonly delayMs: number,
    private readonly capacity = 8,
    private readonly deadlineMs = 120_000,
    private readonly clock: Clock = systemClock,
  ) {}

  enqueue<T>(operation: (context: SendContext) => Promise<T>, deadlineMs = this.deadlineMs): Promise<T> {
    if (this.closed) return Promise.reject(new BridgeError(503, "shutting_down", "The bridge is shutting down", true));
    if (this.waiting.length + Number(this.active !== null) >= this.capacity) {
      return Promise.reject(new BridgeError(503, "queue_full", "The send queue is full", true));
    }
    return new Promise<T>((resolve, reject) => {
      const entry: Entry = {
        run: operation, resolve: (value) => resolve(value as T), reject,
        controller: new AbortController(), submitted: false, replied: false,
      };
      entry.timer = this.clock.setTimeout(() => {
        this.cancel(entry, new BridgeError(504, "send_deadline", "The send deadline expired before submission", true));
        const index = this.waiting.indexOf(entry);
        if (index !== -1) this.waiting.splice(index, 1);
      }, deadlineMs);
      this.waiting.push(entry);
      this.pump();
    });
  }

  private cancel(entry: Entry, error: BridgeError): void {
    if (entry.replied) return;
    entry.replied = true;
    entry.controller.abort();
    this.clock.clearTimeout(entry.timer);
    entry.reject(entry.submitted ? outcomeUnknown() : error);
  }

  private pump(): void {
    if (this.closed || this.active || !this.waiting.length) return;
    const remaining = this.cooldownUntil - this.clock.now();
    if (remaining > 0) {
      this.clock.clearTimeout(this.cooldownTimer);
      this.cooldownTimer = this.clock.setTimeout(() => this.pump(), remaining);
      return;
    }
    const entry = this.waiting.shift()!;
    this.active = entry;
    const context: SendContext = {
      signal: entry.controller.signal,
      get submitted() { return entry.submitted; },
      assertActive: () => {
        if (entry.controller.signal.aborted) {
          throw entry.submitted ? outcomeUnknown() : new BridgeError(503, "send_cancelled", "The send was cancelled before submission", true);
        }
      },
      markSubmitted: () => { context.assertActive(); entry.submitted = true; },
    };
    void Promise.resolve().then(() => { context.assertActive(); return entry.run(context); }).then(
      (value) => {
        if (!entry.replied) { entry.replied = true; entry.resolve(value); }
      },
      (error: unknown) => {
        if (!entry.replied) { entry.replied = true; entry.reject(entry.submitted ? outcomeUnknown() : error); }
      },
    ).finally(() => {
      this.clock.clearTimeout(entry.timer);
      this.active = null;
      if (entry.submitted) this.cooldownUntil = this.clock.now() + this.delayMs;
      this.pump();
    }).catch(() => undefined);
  }

  close(): void {
    this.closed = true;
    this.clock.clearTimeout(this.cooldownTimer);
    const error = new BridgeError(503, "shutting_down", "The bridge is shutting down", true);
    for (const entry of this.waiting.splice(0)) this.cancel(entry, error);
    if (this.active) this.cancel(this.active, error);
  }
}
