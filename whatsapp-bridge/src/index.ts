import "dotenv/config";
import { loadConfig } from "./config.js";
import { WhatsappClient } from "./client/whatsapp-client.js";
import { closeApp, createApp, startServer } from "./server/app.js";
import { validateAllowedRoots } from "./domain/path-validation.js";
import { bounded, systemClock } from "./domain/clock.js";
import { BridgeError } from "./domain/errors.js";

async function main() {
  const config = loadConfig();
  config.allowedRoots = await bounded(validateAllowedRoots(config.allowedRoots), config.fileReadTimeoutMs, systemClock);
  const whatsapp = new WhatsappClient(config);
  const app = createApp(config, whatsapp);

  let server: Awaited<ReturnType<typeof startServer>>;
  try {
    server = await startServer(config, app);
  } catch (error) {
    await whatsapp.close().catch(() => undefined);
    throw error;
  }
  console.info(`WhatsApp bridge listening on http://${config.host}:${config.port}`);

  try {
    await whatsapp.start();
    console.info("WhatsApp session initializing; check /status for readiness");
  } catch (error) {
    closeApp(app);
    server.close();
    await whatsapp.close().catch(() => undefined);
    throw error;
  }

  let stopping = false;
  const shutdown = async (signal: string) => {
    if (stopping) return;
    stopping = true;
    console.info(`Stopping WhatsApp bridge (${signal})`);
    closeApp(app);
    server.close();
    await whatsapp.close();
    // Pending HTTP sends have been rejected. Let their sanitized replies flush.
    server.closeIdleConnections();
  };
  process.once("SIGINT", () => void shutdown("SIGINT").catch(() => { process.exitCode = 1; }));
  process.once("SIGTERM", () => void shutdown("SIGTERM").catch(() => { process.exitCode = 1; }));
}

main().catch((error: unknown) => {
  const reason = error instanceof BridgeError
    ? error.message
    : "check its local configuration and browser installation";
  console.error(`WhatsApp bridge could not start: ${reason}`);
  process.exitCode = 1;
});
