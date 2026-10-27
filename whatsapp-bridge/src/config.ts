import path from "node:path";

export interface BridgeConfig {
  host: "127.0.0.1" | "localhost" | "::1";
  port: number;
  runtimeDir: string;
  allowedRoots: string[];
  sendDelayMs: number;
  /** How long the contact list stays cached before Chrome is asked again. */
  contactsCacheMs: number;
  contactsTimeoutMs: number;
  initTimeoutMs: number;
  authenticatedTimeoutMs: number;
  destroyTimeoutMs: number;
  retryDelaysMs: readonly number[];
  sendCapacity: number;
  sendDeadlineMs: number;
  fileReadTimeoutMs: number;
  headless: boolean;
  executablePath: string | undefined;
  apiKey: string | undefined;
  corsOrigins: string[];
}

const loopbackHosts = new Set(["127.0.0.1", "localhost", "::1"]);

function listValue(value: string | undefined): string[] {
  return (value ?? "")
    .split(/[|;]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function positiveNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value ?? fallback);
  if (!Number.isSafeInteger(parsed) || parsed < 0 || parsed > 2_147_483_647) throw new Error("Invalid bridge numeric configuration");
  return parsed;
}

function nonzeroNumber(value: string | undefined, fallback: number): number {
  const parsed = positiveNumber(value, fallback);
  if (!parsed) throw new Error("Invalid bridge numeric configuration");
  return parsed;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): BridgeConfig {
  const configuredHost = env.WHATSAPP_BRIDGE_HOST ?? "127.0.0.1";
  if (!loopbackHosts.has(configuredHost)) {
    throw new Error("WHATSAPP_BRIDGE_HOST must be a loopback address");
  }
  const runtimeDir = path.resolve(env.WHATSAPP_RUNTIME_DIR ?? path.join(process.cwd(), "runtime"));
  const port = Number(env.WHATSAPP_BRIDGE_PORT ?? "3001");
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid bridge port");
  return {
    host: configuredHost as BridgeConfig["host"],
    port,
    runtimeDir,
    allowedRoots: listValue(env.WHATSAPP_ALLOWED_ROOTS).map((root) => path.resolve(root)),
    sendDelayMs: positiveNumber(env.WHATSAPP_SEND_DELAY_MS, 1200),
    contactsCacheMs: positiveNumber(env.WHATSAPP_CONTACTS_CACHE_MS, 60_000),
    contactsTimeoutMs: nonzeroNumber(env.WHATSAPP_CONTACTS_TIMEOUT_MS, 30_000),
    initTimeoutMs: nonzeroNumber(env.WHATSAPP_INIT_TIMEOUT_MS, 90_000),
    authenticatedTimeoutMs: nonzeroNumber(env.WHATSAPP_AUTHENTICATED_TIMEOUT_MS, 90_000),
    destroyTimeoutMs: nonzeroNumber(env.WHATSAPP_DESTROY_TIMEOUT_MS, 10_000),
    retryDelaysMs: [5_000, 15_000, 45_000],
    sendCapacity: nonzeroNumber(env.WHATSAPP_SEND_CAPACITY, 8),
    sendDeadlineMs: nonzeroNumber(env.WHATSAPP_SEND_DEADLINE_MS, 120_000),
    fileReadTimeoutMs: nonzeroNumber(env.WHATSAPP_FILE_READ_TIMEOUT_MS, 10_000),
    headless: (env.WHATSAPP_HEADLESS ?? "true").toLowerCase() !== "false",
    executablePath: env.WHATSAPP_EXECUTABLE_PATH?.trim() || undefined,
    apiKey: env.WHATSAPP_BRIDGE_API_KEY?.trim() || undefined,
    corsOrigins: listValue(env.WHATSAPP_CORS_ORIGINS),
  };
}
