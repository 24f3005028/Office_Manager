import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm, open, symlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { MAX_PDF_BYTES, PathValidationError, isWithinAllowedRoot, readPdf, validateAllowedRoots, validatePdfPath, validateUploadedPdf } from "./path-validation.js";

async function temporary() { return mkdtemp(path.join(os.tmpdir(), "agent-tmp", "bridge-pdf-test-")); }

test("reads and validates a real-shaped mock PDF asynchronously within a root", async () => {
  const root = await temporary();
  try {
    const file = path.join(root, "mock.pdf");
    await writeFile(file, "%PDF-1.7\nmock fixture");
    assert.equal(await validatePdfPath(file, [root]), file);
    assert.equal((await readPdf(file, () => [root], 1000)).buffer.toString(), "%PDF-1.7\nmock fixture");
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("rejects outside roots, directories, renamed non-PDF content and empty allowed roots", async () => {
  const root = await temporary();
  try {
    const inside = path.join(root, "inside"); await mkdir(inside);
    const file = path.join(root, "mock.pdf"); await writeFile(file, "%PDF-mock");
    await assert.rejects(validatePdfPath(file, [inside]), PathValidationError);
    await assert.rejects(validatePdfPath(file, []), PathValidationError);
    const dir = path.join(inside, "directory.pdf"); await mkdir(dir);
    await assert.rejects(validatePdfPath(dir, [inside]), PathValidationError);
    await writeFile(file, "not a PDF");
    await assert.rejects(readPdf(file, () => [root], 1000), PathValidationError);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("path and upload flows enforce the same 25 MiB size and PDF signature", async () => {
  const root = await temporary();
  try {
    const file = path.join(root, "large.pdf");
    const handle = await open(file, "w");
    await handle.writeFile("%PDF-"); await handle.truncate(MAX_PDF_BYTES + 1); await handle.close();
    await assert.rejects(validatePdfPath(file, [root]), PathValidationError);
    const upload = Buffer.alloc(MAX_PDF_BYTES + 1); upload.write("%PDF-");
    assert.throws(() => validateUploadedPdf("large.pdf", upload), PathValidationError);
    assert.throws(() => validateUploadedPdf("mock.pdf", Buffer.from("other")), PathValidationError);
    assert.throws(() => validateUploadedPdf("mock.txt", Buffer.from("%PDF-")), PathValidationError);
    validateUploadedPdf("mock.PDF", upload.subarray(0, MAX_PDF_BYTES));
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("allowed roots validation is all-or-nothing and permits []", async () => {
  const root = await temporary();
  try {
    assert.deepEqual(await validateAllowedRoots([]), []);
    assert.deepEqual(await validateAllowedRoots([root, root]), [root]);
    await assert.rejects(validateAllowedRoots([root, "relative-path"]));
    await assert.rejects(validateAllowedRoots([root, null]));
    await assert.rejects(validateAllowedRoots([root, path.join(root, "missing")]));
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("execution reads consult current roots and respect an already cancelled operation", async () => {
  const root = await temporary();
  try {
    const file = path.join(root, "mock.pdf"); await writeFile(file, "%PDF-mock");
    await validatePdfPath(file, [root]);
    await assert.rejects(readPdf(file, () => [], 1000), PathValidationError);
    const cancelled = new AbortController(); cancelled.abort();
    await assert.rejects(readPdf(file, () => [root], 1000, cancelled.signal), PathValidationError);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("directory junction/symlink escape and similarly prefixed siblings are rejected", async () => {
  const root = await temporary();
  try {
    const inside = path.join(root, "allowed"), outside = path.join(root, "allowed-other");
    await mkdir(inside); await mkdir(outside);
    await writeFile(path.join(outside, "mock.pdf"), "%PDF-mock");
    await symlink(outside, path.join(inside, "escape"), process.platform === "win32" ? "junction" : "dir");
    await assert.rejects(validatePdfPath(path.join(inside, "escape", "mock.pdf"), [inside]), PathValidationError);
    assert.equal(isWithinAllowedRoot(path.join(outside, "mock.pdf"), inside), false);
  } finally { await rm(root, { recursive: true, force: true }); }
});
