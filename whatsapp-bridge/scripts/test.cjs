const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

function tests(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? tests(file) : entry.name.endsWith(".test.ts") ? [file] : [];
  });
}

// Explicit discovery works on Windows too and never imports the real entry point.
const result = spawnSync(process.execPath, ["--import", "tsx", "--test", ...tests(path.join(__dirname, "..", "src"))], { stdio: "inherit" });
process.exitCode = result.status ?? 1;
