import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const { patchFile } = createRequire(import.meta.url)("../../scripts/patch-wwebjs-media-id.cjs") as {
  patchFile(source: string): { status: string; content?: string };
};
const { patchFile: patchMessageId } = createRequire(import.meta.url)("../../scripts/patch-wwebjs-message-id.cjs") as {
  patchFile(source: string): { status: string; content?: string };
};
const messageSource = `window.WWebJS.sendMessage = async (chat, content, options = {}) => {
        const newMsgKey = new (window.require('WAWebMsgKey'))({
            from: from,
            to: chat.id,
            id: newId,
        });
        await msgPromise;
        return window
            .require('WAWebCollections')
            .Msg.get(newMsgKey._serialized);
    };
    window.WWebJS.editMessage = async (msg, content, options = {}) => {
        return window.require('WAWebCollections').Msg.get(newMsgKey._serialized);
    };
`;
const source = `window.WWebJS.sendMessage = async (chat, content, options = {}) => {
        const message = {
            ...mediaOptions,
            ...extraOptions,
        };
        send(message);
    };
    window.WWebJS.editMessage = async () => {};
`;

test("patch detection is scoped, idempotent and accepts LF or CRLF without launching the library", () => {
  for (const input of [source, source.replaceAll("\n", "\r\n"), `// delete message.__x_id;\n${source}`]) {
    const result = patchFile(input);
    assert.equal(result.status, "patched");
    assert.equal(patchFile(result.content!).status, "already-patched");
  }
});

test("patch refuses unfamiliar or ambiguous source instead of silently claiming success", () => {
  assert.equal(patchFile("delete message.__x_id;").status, "incompatible");
  assert.equal(patchFile(source.replace("...extraOptions,", "...unknownShape,")).status, "incompatible");
});

test("message-id patch detects the send lookup, is idempotent and leaves other lookups alone", () => {
  for (const input of [messageSource, messageSource.replaceAll("\n", "\r\n")]) {
    const result = patchMessageId(input);
    assert.equal(result.status, "patched");
    assert.match(result.content!, /\.Msg\.get\(newMsgKey\._serialized \?\? newMsgKey\.\$1\)/);
    assert.equal(patchMessageId(result.content!).status, "already-patched");
  }
  const patched = patchMessageId(messageSource).content!;
  const editBody = patched.slice(patched.indexOf("window.WWebJS.editMessage"));
  assert.match(editBody, /\.Msg\.get\(newMsgKey\._serialized\)/);
});

test("message-id patch refuses unfamiliar or ambiguous source instead of silently claiming success", () => {
  assert.equal(patchMessageId("delete message.__x_id;").status, "incompatible");
  assert.equal(
    patchMessageId(messageSource.replace(
      "await msgPromise;",
      "await msgPromise;\n        return window.require('WAWebCollections').Msg.get(newMsgKey._serialized);",
    )).status,
    "incompatible",
  );
  assert.equal(
    patchMessageId(messageSource.replace("window.WWebJS.editMessage", "window.WWebJS.otherMessage")).status,
    "incompatible",
  );
});
