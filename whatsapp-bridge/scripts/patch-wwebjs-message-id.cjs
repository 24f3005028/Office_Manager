/**
 * Patches the installed whatsapp-web.js so sent-message receipts survive the
 * WhatsApp Web rename of a message key's serialized property from `_serialized`
 * to `$1`.
 *
 * The pinned library ends sendMessage with:
 *   Msg.get(newMsgKey._serialized)
 * On current WhatsApp Web builds `_serialized` is undefined, so that lookup
 * returns undefined even though WhatsApp accepted the message. Prefer the
 * legacy name and fall back to `$1`, matching the upstream fix.
 *
 * Runs via `postinstall`. Idempotent: skips when the fix is already present and
 * fails closed on an unfamiliar code shape. --check verifies without writing.
 * It never imports the library, launches a browser, or accesses runtime data.
 */

const fs = require("node:fs");
const path = require("node:path");

const TARGET = path.join(
  __dirname,
  "..",
  "node_modules",
  "whatsapp-web.js",
  "src",
  "util",
  "Injected",
  "Utils.js",
);

const LEGACY = /\.Msg\.get\(\s*newMsgKey\._serialized\s*\)/;
const PATCHED = /\.Msg\.get\(\s*newMsgKey\._serialized\s*\?\?\s*newMsgKey\.\$1\s*\)/;
const UPSTREAM = /\.Msg\.get\(\s*window\.WWebJS\.getMsgKeyId\(newMsgKey\)\s*\)/;
const DIRECT = /\.Msg\.get\(\s*newMsgKey\.\$1\s*\)/;

function patchFile(source) {
  const start = source.indexOf("window.WWebJS.sendMessage = async");
  const end = source.indexOf("window.WWebJS.editMessage = async", start);
  if (start < 0 || end < 0) return { status: "incompatible" };
  const body = source.slice(start, end);
  if (PATCHED.test(body) || UPSTREAM.test(body) || DIRECT.test(body)) {
    return { status: "already-patched" };
  }
  const matches = [...body.matchAll(new RegExp(LEGACY.source, "g"))];
  if (matches.length !== 1) return { status: "incompatible" };
  const absolute = start + matches[0].index;
  const replacement = ".Msg.get(newMsgKey._serialized ?? newMsgKey.$1)";
  return {
    status: "patched",
    content:
      source.slice(0, absolute) +
      replacement +
      source.slice(absolute + matches[0][0].length),
  };
}

function main() {
  const check = process.argv.includes("--check");
  if (!fs.existsSync(TARGET)) throw new Error("missing-target");
  const result = patchFile(fs.readFileSync(TARGET, "utf8"));
  if (result.status === "incompatible") throw new Error("incompatible-source");
  if (check && result.status !== "already-patched") throw new Error("patch-required");
  if (!check && result.status === "patched") fs.writeFileSync(TARGET, result.content);
  console.log(`patch-wwebjs-message-id: ${check ? "verified" : result.status}`);
}

module.exports = { patchFile };
if (require.main === module) {
  try {
    main();
  } catch {
    console.error(
      "patch-wwebjs-message-id: verification failed; review installed source",
    );
    process.exitCode = 1;
  }
}
