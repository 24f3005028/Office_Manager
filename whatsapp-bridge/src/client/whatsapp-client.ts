import whatsappWeb from "whatsapp-web.js";
import * as QRCode from "qrcode";
import type { BridgeConfig } from "../config.js";
import { filterContacts, isLid, isPhoneId, isRoutingId, savedName, serializedId, type RawContact } from "../domain/contact-filter.js";
import { bounded, systemClock, type Clock } from "../domain/clock.js";
import { BridgeError, BridgeNotReadyError, outcomeUnknown } from "../domain/errors.js";
import type { BridgeContact, BridgeState, BridgeStatus } from "../domain/types.js";
import type { SendContext } from "../queue/send-queue.js";

export { BridgeNotReadyError } from "../domain/errors.js";

export interface ClientAdapter {
  on(event: string, listener: (...args: any[]) => void): unknown;
  initialize(): Promise<void>;
  destroy(): Promise<void>;
  info?: { wid?: { _serialized?: string } };
  getContacts(): Promise<RawContact[]>;
  getContactLidAndPhone(ids: string[]): Promise<{ lid?: string; pn?: string }[]>;
  sendMessage(id: string, content: string | whatsappWeb.MessageMedia, options: whatsappWeb.MessageSendOptions): Promise<unknown>;
}

export interface ClientDependencies {
  clientFactory?: () => ClientAdapter;
  qrToSvg?: (qr: string) => Promise<string>;
  clock?: Clock;
}

export interface SessionSnapshot { generation: number; account: string }

interface Session {
  sdk: ClientAdapter;
  generation: number;
  active: boolean;
  initialized: Promise<void>;
  settled: boolean;
  disposed: boolean;
  watchdog?: unknown;
  authenticated: boolean;
  wasReady: boolean;
}

/** The upstream LocalAuth.logout() deletes the auth directory. Recovery here
 * deliberately preserves it, including when the SDK reports a remote logout. */
export class PreservingLocalAuth extends whatsappWeb.LocalAuth {
  override logout = async (): Promise<void> => { /* Explicit operator repair only. */ };
}

export class WhatsappClient {
  private readonly clock: Clock;
  private readonly factory: () => ClientAdapter;
  private readonly qrToSvg: (qr: string) => Promise<string>;
  private session: Session | null = null;
  private state: BridgeState = "starting";
  private initializing = false;
  private action: BridgeStatus["requires_action"] = null;
  private message: string | null = null;
  private generation = 0;
  private qrRevision = 0;
  private qrSvg: string | null = null;
  private hasAuthenticated = false;
  private attempt = 0;
  private scheduled = false;
  private closed = false;
  private tail: Promise<void> = Promise.resolve();
  private closePromise: Promise<void> | null = null;
  private cancelDelay: (() => void) | null = null;
  private contactsCache: { generation: number; contacts: BridgeContact[]; cachedAt: number } | null = null;
  private contactsPromise: Promise<BridgeContact[]> | null = null;
  private readonly lidCache = new Map<string, { phone: string; expires: number }>();

  constructor(private readonly config: BridgeConfig, dependencies: ClientDependencies = {}) {
    this.clock = dependencies.clock ?? systemClock;
    this.qrToSvg = dependencies.qrToSvg ?? ((qr) => QRCode.toString(qr, { type: "svg", margin: 1 }));
    this.factory = dependencies.clientFactory ?? (() => {
      const sdk = new whatsappWeb.Client({
        authStrategy: new PreservingLocalAuth({ clientId: "office-dashboard", dataPath: config.runtimeDir }),
        puppeteer: {
          headless: config.headless,
          args: ["--no-sandbox", "--disable-setuid-sandbox"],
          ...(config.executablePath ? { executablePath: config.executablePath } : { channel: "chrome" as const }),
        },
      });
      // destroy() in 1.34.7 assumes a browser exists, even before initialize().
      return {
        on: (event, listener) => sdk.on(event, listener),
        initialize: () => sdk.initialize(),
        destroy: async () => { if (sdk.pupBrowser) await sdk.destroy(); },
        get info() { return sdk.info; },
        getContacts: () => sdk.getContacts(),
        getContactLidAndPhone: (ids) => sdk.getContactLidAndPhone(ids),
        sendMessage: (id, content, options) => sdk.sendMessage(id, content, options),
      };
    });
  }

  async start(): Promise<void> {
    if (this.closed) throw new BridgeError(503, "shutting_down", "The bridge is shutting down", true);
    if (this.scheduled || this.initializing || ["ready", "qr", "auth_failure"].includes(this.state)) return;
    this.attempt = 0;
    this.scheduleAttempt(0);
  }

  async reconnect(): Promise<void> {
    if (this.closed) throw new BridgeError(503, "shutting_down", "The bridge is shutting down", true);
    if (this.scheduled || this.initializing) return;
    this.attempt = 0;
    this.scheduleAttempt(0);
  }

  private isCurrent(session: Session): boolean {
    return !this.closed && session.active && session === this.session && session.generation === this.generation;
  }

  private invalidate(): void {
    if (this.session) {
      this.session.active = false;
      this.clock.clearTimeout(this.session.watchdog);
    }
    this.qrRevision++;
    this.qrSvg = null;
    this.contactsCache = null;
    this.contactsPromise = null;
    this.lidCache.clear();
  }

  private repair(): void {
    this.invalidate();
    this.state = "error";
    this.initializing = false;
    this.action = "repair";
    this.message = "Startup could not complete safely. Check the local browser/session and reconnect; stored authentication was preserved.";
  }

  private scheduleAttempt(delay: number): void {
    this.invalidate();
    const generation = ++this.generation;
    this.scheduled = true;
    this.initializing = true;
    this.state = delay ? "retrying" : "starting";
    this.action = null;
    this.message = delay ? "Retrying the saved WhatsApp session." : "Starting the saved WhatsApp session.";
    this.tail = this.tail.then(async () => {
      if (this.closed || generation !== this.generation) return;
      if (this.session) await this.dispose(this.session);
      if (delay) await new Promise<void>((resolve) => {
        const timer = this.clock.setTimeout(resolve, delay);
        this.cancelDelay = () => { this.clock.clearTimeout(timer); resolve(); };
      });
      this.cancelDelay = null;
      if (this.closed || generation !== this.generation) return;
      const session: Session = {
        sdk: this.factory(), generation, active: true, initialized: Promise.resolve(),
        settled: false, disposed: false, authenticated: false, wasReady: false,
      };
      this.session = session;
      this.attach(session);
      this.armWatchdog(session, this.config.initTimeoutMs);
      session.initialized = Promise.resolve().then(() => session.sdk.initialize());
      void session.initialized.then(
        () => { session.settled = true; this.lateCleanup(session); },
        () => { session.settled = true; if (this.isCurrent(session)) this.failed(session); this.lateCleanup(session); },
      ).catch(() => { if (this.isCurrent(session)) this.repair(); });
    }).catch(() => {
      if (!this.closed && generation === this.generation) this.repair();
    }).finally(() => {
      if (generation === this.generation) this.scheduled = false;
    });
  }

  private lateCleanup(session: Session): void {
    if (session.active || session.disposed) return;
    this.tail = this.tail.then(() => this.dispose(session)).catch(() => undefined);
  }

  private async dispose(session: Session): Promise<void> {
    if (session.disposed) return;
    session.active = false;
    this.clock.clearTimeout(session.watchdog);
    const wasPending = !session.settled;
    await bounded(Promise.resolve().then(() => session.sdk.destroy()), this.config.destroyTimeoutMs, this.clock);
    // Never launch another browser while an older initialize() can still launch
    // or attach one. A hung initializer fails closed, and is cleaned up if late.
    if (wasPending) {
      await bounded(session.initialized.catch(() => undefined), this.config.destroyTimeoutMs, this.clock);
      await bounded(Promise.resolve().then(() => session.sdk.destroy()), this.config.destroyTimeoutMs, this.clock);
    }
    session.disposed = true;
  }

  private armWatchdog(session: Session, ms: number): void {
    this.clock.clearTimeout(session.watchdog);
    session.watchdog = this.clock.setTimeout(() => {
      if (this.isCurrent(session)) this.failed(session);
    }, ms);
  }

  private failed(session: Session): void {
    if (!this.isCurrent(session)) return;
    const delay = this.config.retryDelaysMs[this.attempt++];
    if (delay === undefined) this.repair();
    else this.scheduleAttempt(delay);
  }

  private attach(session: Session): void {
    const on = (event: string, callback: (...args: any[]) => void) => {
      session.sdk.on(event, (...args: any[]) => {
        if (!this.isCurrent(session)) return;
        try { callback(...args); } catch { this.failed(session); }
      });
    };
    on("qr", (qr: string) => {
      this.clock.clearTimeout(session.watchdog);
      this.state = "qr";
      this.initializing = false;
      this.action = this.hasAuthenticated ? "relink" : "link";
      this.message = "Scan the QR code in WhatsApp linked devices.";
      this.qrSvg = null;
      const revision = ++this.qrRevision;
      void Promise.resolve().then(() => this.qrToSvg(qr)).then((svg) => {
        if (this.isCurrent(session) && revision === this.qrRevision && this.state === "qr") this.qrSvg = svg;
      }, () => {
        if (this.isCurrent(session) && revision === this.qrRevision) this.repair();
      });
    });
    on("authenticated", () => {
      if (session.wasReady || session.authenticated) return;
      session.authenticated = true;
      this.hasAuthenticated = true;
      this.state = "authenticated";
      this.initializing = true;
      this.action = null;
      this.message = "Authenticated; waiting for WhatsApp to become ready.";
      this.qrSvg = null;
      this.qrRevision++;
      this.armWatchdog(session, this.config.authenticatedTimeoutMs);
    });
    on("ready", () => {
      session.wasReady = true;
      this.hasAuthenticated = true;
      this.clock.clearTimeout(session.watchdog);
      this.state = "ready";
      this.initializing = false;
      this.action = null;
      this.message = null;
      this.qrSvg = null;
      this.qrRevision++;
      this.contactsCache = null;
      this.attempt = 0;
    });
    on("auth_failure", () => this.authenticationFailed(session));
    on("disconnected", (reason: string) => {
      if (["LOGOUT", "UNPAIRED", "UNPAIRED_IDLE"].includes(reason)) return this.authenticationFailed(session);
      this.invalidate();
      this.state = "disconnected";
      this.initializing = false;
      this.action = null;
      this.message = "WhatsApp disconnected. Reconnect to resume the saved session.";
    });
    on("error", () => this.failed(session));
    on("loading_screen", () => {
      if (this.initializing) this.message = "Loading the saved WhatsApp session.";
    });
    on("change_state", (state: string) => {
      if (["UNPAIRED", "UNPAIRED_IDLE"].includes(state)) this.authenticationFailed(session);
      else if (state === "TIMEOUT" && session.wasReady) {
        this.state = "disconnected";
        this.contactsCache = null;
        this.message = "WhatsApp connection timed out. Reconnect if it does not recover.";
      } else if (state === "CONNECTED" && session.wasReady) {
        this.state = "ready";
        this.message = null;
      }
    });
  }

  private authenticationFailed(session: Session): void {
    this.clock.clearTimeout(session.watchdog);
    this.invalidate();
    this.state = "auth_failure";
    this.initializing = false;
    this.action = this.hasAuthenticated ? "relink" : "link";
    this.message = "WhatsApp authentication is required. Reconnect to obtain a linking code.";
  }

  status(): BridgeStatus {
    return {
      status: this.state, connected: this.state === "ready", qr_available: this.qrSvg !== null,
      initializing: this.initializing, requires_action: this.action, message: this.message,
      generation: this.generation, qr_revision: this.qrRevision,
    };
  }

  qr(): string | null { return this.qrSvg; }

  snapshot(expectedGeneration?: number): SessionSnapshot {
    const session = this.session;
    if (!session || !this.isCurrent(session) || this.state !== "ready") throw new BridgeNotReadyError();
    if (expectedGeneration !== undefined && expectedGeneration !== this.generation) {
      throw new BridgeError(409, "stale_generation", "The WhatsApp session has changed", true);
    }
    const account = session.sdk.info?.wid?._serialized;
    if (!account || !isRoutingId(account)) throw new BridgeNotReadyError();
    return { generation: this.generation, account };
  }

  assertSnapshot(snapshot: SessionSnapshot): void {
    const current = this.snapshot(snapshot.generation);
    if (current.account !== snapshot.account) throw new BridgeError(409, "session_changed", "The WhatsApp account has changed", true);
  }

  async resolveRecipient(snapshot: SessionSnapshot, contactId: string): Promise<string> {
    this.assertSnapshot(snapshot);
    if (isPhoneId(contactId)) return contactId;
    if (!isLid(contactId)) throw new BridgeError(400, "invalid_contact", "Invalid contact routing identity");
    const cached = this.lidCache.get(contactId);
    if (cached && cached.expires > this.clock.now()) return cached.phone;
    const result = await bounded(this.session!.sdk.getContactLidAndPhone([contactId]), this.config.contactsTimeoutMs, this.clock);
    this.assertSnapshot(snapshot);
    const mapping = result.find((entry) => entry.lid === contactId && typeof entry.pn === "string" && isPhoneId(entry.pn));
    if (!mapping?.pn) throw new BridgeError(400, "unresolved_contact", "The contact identity could not be verified");
    this.lidCache.set(contactId, { phone: mapping.pn, expires: this.clock.now() + this.config.contactsCacheMs });
    return mapping.pn;
  }

  async contacts(): Promise<BridgeContact[]> {
    const snapshot = this.snapshot();
    const cache = this.contactsCache;
    if (cache?.generation === snapshot.generation) {
      if (this.clock.now() - cache.cachedAt >= this.config.contactsCacheMs && !this.contactsPromise) {
        void this.fetchContacts(snapshot).catch(() => undefined);
      }
      return cache.contacts;
    }
    return this.contactsPromise ?? this.fetchContacts(snapshot);
  }

  private fetchContacts(snapshot: SessionSnapshot): Promise<BridgeContact[]> {
    const sdk = this.session!.sdk;
    let active = true;
    const check = () => {
      this.assertSnapshot(snapshot);
      if (!active) throw new BridgeError(504, "contacts_timeout", "Contact refresh timed out", true);
    };
    const work = (async () => {
      const raw = await sdk.getContacts();
      check();
      const ids = [...new Set([...raw.filter((c) => savedName(c) && !c.isGroup && !c.isMe).map(serializedId), snapshot.account].filter(isLid))];
      const mappings = new Map<string, string>();
      const missing: string[] = [];
      for (const id of ids) {
        const cached = this.lidCache.get(id);
        if (cached && cached.expires > this.clock.now()) mappings.set(id, cached.phone);
        else missing.push(id);
      }
      for (let i = 0; i < missing.length; i += 100) {
        check();
        const batch = missing.slice(i, i + 100);
        const results = await sdk.getContactLidAndPhone(batch);
        check();
        for (const { lid, pn } of results) {
          if (!lid || !pn || !batch.includes(lid) || !isLid(lid) || !isPhoneId(pn)) continue;
          mappings.set(lid, pn);
          this.lidCache.delete(lid);
          this.lidCache.set(lid, { phone: pn, expires: this.clock.now() + this.config.contactsCacheMs });
          if (this.lidCache.size > 2048) this.lidCache.delete(this.lidCache.keys().next().value!);
        }
      }
      check();
      return filterContacts(raw, snapshot.account, mappings);
    })();
    const promise = bounded(work, this.config.contactsTimeoutMs, this.clock).then((contacts) => {
      check();
      this.contactsCache = { generation: snapshot.generation, contacts, cachedAt: this.clock.now() };
      return contacts;
    }).catch((error: unknown) => {
      if (error instanceof BridgeError) throw error;
      throw new BridgeError(502, "contacts_unavailable", "Contacts are temporarily unavailable", true);
    }).finally(() => {
      active = false;
      if (this.contactsPromise === promise) this.contactsPromise = null;
    });
    this.contactsPromise = promise;
    return promise;
  }

  async sendText(snapshot: SessionSnapshot, contactId: string, text: string, context: SendContext): Promise<string> {
    return this.submit(snapshot, contactId, text, { waitUntilMsgSent: true }, context);
  }

  async sendBuffer(snapshot: SessionSnapshot, contactId: string, buffer: Buffer, filename: string, caption: string | undefined, context: SendContext): Promise<string> {
    const media = new whatsappWeb.MessageMedia("application/pdf", buffer.toString("base64"), filename);
    return this.submit(snapshot, contactId, media, { caption, waitUntilMsgSent: true, sendMediaAsDocument: true }, context);
  }

  private async submit(snapshot: SessionSnapshot, contactId: string, content: string | whatsappWeb.MessageMedia, options: whatsappWeb.MessageSendOptions, context: SendContext): Promise<string> {
    this.assertSnapshot(snapshot);
    context.assertActive();
    const sdk = this.session!.sdk;
    const recipient = await this.resolveRecipient(snapshot, contactId);
    context.assertActive();
    context.markSubmitted();
    try {
      const result = await sdk.sendMessage(recipient, content, options) as {
        id?: { _serialized?: unknown; $1?: unknown };
      } | null | undefined;
      this.assertSnapshot(snapshot);
      context.assertActive();
      // WhatsApp Web renamed the serialized message-key property from
      // `_serialized` to `$1`. Accept either shape; prefer a non-empty legacy
      // value when both are present.
      const id = [result?.id?._serialized, result?.id?.$1].find(
        (value): value is string => typeof value === "string" && value.trim() !== "",
      );
      if (!id || id.length > 512) throw outcomeUnknown();
      return id;
    } catch { throw outcomeUnknown(); }
  }

  close(): Promise<void> {
    if (this.closePromise) return this.closePromise;
    this.closed = true;
    this.generation++;
    this.invalidate();
    this.cancelDelay?.();
    this.initializing = false;
    this.state = "disconnected";
    this.action = null;
    this.message = "The bridge is shutting down.";
    this.closePromise = this.tail.then(async () => {
      if (this.session) await this.dispose(this.session);
    }).catch(() => undefined);
    this.tail = this.closePromise;
    return this.closePromise;
  }
}
