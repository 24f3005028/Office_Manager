import { EventEmitter } from "node:events";
import path from "node:path";
import os from "node:os";
import type whatsappWeb from "whatsapp-web.js";
import { loadConfig, type BridgeConfig } from "../config.js";
import { WhatsappClient, type ClientAdapter } from "../client/whatsapp-client.js";
import type { Clock } from "../domain/clock.js";
import type { RawContact } from "../domain/contact-filter.js";
import { BridgeError, outcomeUnknown } from "../domain/errors.js";
import type { Journal, OperationBinding } from "../queue/operation-journal.js";

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

export async function flush(): Promise<void> { for (let i = 0; i < 50; i++) await Promise.resolve(); }

export class FakeClock implements Clock {
  private time = 0;
  private id = 0;
  private timers = new Map<number, { at: number; callback: () => void }>();
  now(): number { return this.time; }
  setTimeout(callback: () => void, ms: number): number {
    const id = ++this.id;
    this.timers.set(id, { at: this.time + ms, callback });
    return id;
  }
  clearTimeout(timer: unknown): void { this.timers.delete(timer as number); }
  async advance(ms: number): Promise<void> {
    await flush();
    const target = this.time + ms;
    for (let safety = 0; safety < 1000; safety++) {
      const next = [...this.timers.entries()].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) { this.time = target; await flush(); return; }
      this.time = next[1].at;
      this.timers.delete(next[0]);
      next[1].callback();
      await flush();
    }
    throw new Error("Fake clock did not settle");
  }
}

export function testConfig(overrides: Partial<BridgeConfig> = {}): BridgeConfig {
  return {
    ...loadConfig({ WHATSAPP_RUNTIME_DIR: path.join(os.tmpdir(), "unused-mock-bridge") }),
    initTimeoutMs: 100, authenticatedTimeoutMs: 100, destroyTimeoutMs: 10,
    retryDelaysMs: [10, 20], contactsTimeoutMs: 100, contactsCacheMs: 50,
    sendDelayMs: 0, sendCapacity: 3, sendDeadlineMs: 100,
    ...overrides,
  };
}

export class FakeClient extends EventEmitter implements ClientAdapter {
  info = { wid: { _serialized: "12025550100@c.us" } };
  initializes = 0;
  destroys = 0;
  contactsCalls = 0;
  mappingCalls: string[][] = [];
  sends: { id: string; content: string | whatsappWeb.MessageMedia; options: whatsappWeb.MessageSendOptions }[] = [];
  initializeImpl: () => Promise<void> = async () => undefined;
  destroyImpl: () => Promise<void> = async () => undefined;
  contactsImpl: () => Promise<RawContact[]> = async () => [];
  mappingImpl: (ids: string[]) => Promise<{ lid?: string; pn?: string }[]> = async () => [];
  sendImpl: () => Promise<unknown> = async () => ({ id: { _serialized: "fake-receipt" } });
  async initialize(): Promise<void> { this.initializes++; await this.initializeImpl(); }
  async destroy(): Promise<void> { this.destroys++; await this.destroyImpl(); }
  async getContacts(): Promise<RawContact[]> { this.contactsCalls++; return this.contactsImpl(); }
  async getContactLidAndPhone(ids: string[]) { this.mappingCalls.push(ids); return this.mappingImpl(ids); }
  async sendMessage(id: string, content: string | whatsappWeb.MessageMedia, options: whatsappWeb.MessageSendOptions) {
    this.sends.push({ id, content, options }); return this.sendImpl();
  }
}

export function harness(options: { config?: Partial<BridgeConfig>; create?: () => FakeClient; qr?: (qr: string) => Promise<string> } = {}) {
  const clock = new FakeClock();
  const config = testConfig(options.config);
  const clients: FakeClient[] = [];
  const client = new WhatsappClient(config, {
    clock, qrToSvg: options.qr ?? (async () => "<svg>mock</svg>"),
    clientFactory: () => { const sdk = options.create?.() ?? new FakeClient(); clients.push(sdk); return sdk; },
  });
  return {
    clock, config, clients, client,
    ready: async () => { await client.start(); await flush(); clients.at(-1)!.emit("ready"); await flush(); return clients.at(-1)!; },
  };
}

export class MemoryJournal implements Journal {
  records = new Map<string, { binding: OperationBinding; message?: string }>();
  reserveImpl: () => Promise<void> = async () => undefined;
  completeImpl: () => Promise<void> = async () => undefined;
  async lookup(id: string, binding: OperationBinding): Promise<string | null> {
    const record = this.records.get(id);
    if (!record) return null;
    if (JSON.stringify(record.binding) !== JSON.stringify(binding)) throw new BridgeError(409, "operation_conflict", "Operation conflict");
    if (!record.message) throw outcomeUnknown();
    return record.message;
  }
  async reserve(id: string, binding: OperationBinding): Promise<string | null> {
    await this.reserveImpl();
    const existing = this.records.get(id);
    if (existing) {
      if (existing.message) return existing.message;
      throw outcomeUnknown();
    }
    this.records.set(id, { binding });
    return null;
  }
  async complete(id: string, binding: OperationBinding, message: string): Promise<void> {
    await this.completeImpl();
    this.records.set(id, { binding, message });
  }
}

export const hasCode = (code: string) => (error: unknown): boolean => error instanceof BridgeError && error.code === code;
