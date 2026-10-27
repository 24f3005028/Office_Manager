/**
 * Patches the installed whatsapp-web.js so media/document sends work on current
 * WhatsApp Web builds.
 *
 * Keeps the project's existing MediaData private-ID workaround. Detection is
 * scoped to the actual sendMessage body rather than an arbitrary marker elsewhere.
 *
 * Runs via `postinstall`. Idempotent: skips when the fix is already present and
 * fails closed on an unfamiliar code shape. --check verifies without writing.
 * It never imports the library, launches a browser, or accesses runtime data.
 */

const fs = require("node:fs");
const path = require("node:path");

const MARKER = "delete message.__x_id;";
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

function patchFile(source) {
  const start = source.indexOf("window.WWebJS.sendMessage = async");
  const end = source.indexOf("window.WWebJS.editMessage = async", start);
  if (start < 0 || end < 0) return { status: "incompatible" };
  const body = source.slice(start, end);
  const anchors = [...body.matchAll(/const message = \{[\s\S]*?\.\.\.extraOptions,\r?\n        \};/g)];
  if (anchors.length !== 1) return { status: "incompatible" };
  const anchor = anchors[0];
  const insertion = start + anchor.index + anchor[0].length;
  const after = source.slice(insertion, end).replace(/\/\*[\s\S]*?\*\/|\/\/[^\r\n]*/g, "").trimStart();
  if (after.startsWith(MARKER)) return { status: "already-patched" };
  const newline = source.includes("\r\n") ? "\r\n" : "\n";
  const patched = source.slice(0, insertion) + `${newline}${newline}        ${MARKER}` + source.slice(insertion);
  return { status: "patched", content: patched };
}

function main() {
  const check = process.argv.includes("--check");
  if (!fs.existsSync(TARGET)) throw new Error("missing-target");
  const result = patchFile(fs.readFileSync(TARGET, "utf8"));
  if (result.status === "incompatible") throw new Error("incompatible-source");
  if (check && result.status !== "already-patched") throw new Error("patch-required");
  if (!check && result.status === "patched") fs.writeFileSync(TARGET, result.content);
  console.log(`patch-wwebjs-media-id: ${check ? "verified" : result.status}`);
}

module.exports = { patchFile };
if (require.main === module) {
  try { main(); }
  catch { console.error("patch-wwebjs-media-id: verification failed; review installed source"); process.exitCode = 1; }
}
