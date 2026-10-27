import assert from "node:assert/strict";
import { test } from "node:test";
import { filterContacts, isRoutingId } from "./contact-filter.js";

test("keeps saved contacts only and excludes groups, self and unsupported routing types", () => {
  const result = filterContacts([
    { id: "12025550101@c.us", name: "Saved" },
    { id: "12025550102@c.us", pushname: "Unsaved", isMyContact: false },
    { id: "12025550103@c.us", name: "Explicit unsaved", isMyContact: false },
    { id: "12025550104@c.us", name: "..." },
    { id: "12025550105@c.us", name: "Me", isMe: true },
    { id: "12025550106@c.us", name: "Self ID" },
    ...["1@g.us", "1@broadcast", "1@newsletter"].map((id) => ({ id, name: "Excluded" })),
  ], "12025550106@c.us");
  assert.deepEqual(result.map((c) => c.name), ["Saved"]);
});

test("strict routing never manufactures a phone by stripping letters or using number fallback", () => {
  for (const id of ["15charinternalid0@c.us", "abc12025550101@c.us", "123@c.us", "012025550101@c.us", "1234567890123456@c.us", "12025550101@s.whatsapp.net"]) {
    assert.equal(isRoutingId(id), false);
    assert.deepEqual(filterContacts([{ id, name: "Invalid", number: "+1 202 555 0101" }]), []);
  }
});

test("identity-derived phone wins over inconsistent number fields and supports up to 15 digits", () => {
  const contacts = filterContacts([
    { id: "12025550101@c.us", name: "Customer", number: "9999999999999999" },
    { id: "123456789012345@c.us", name: "Long valid routing ID" },
  ]);
  assert.deepEqual(contacts.map((c) => c.number), ["12025550101", "123456789012345"]);
});

test("verified LID mapping is included; opaque/unverified or malformed mapping is excluded", () => {
  const raw = [
    { id: "lid-token-999999999999999@lid", name: "Mapped" },
    { id: "lid-token-888888888888888@lid", name: "Unmapped", number: "12025550102" },
    { id: "lid-token-777777777777777@lid", name: "Bad mapping" },
  ];
  const result = filterContacts(raw, undefined, new Map([
    ["lid-token-999999999999999@lid", "12025550101@c.us"], ["lid-token-777777777777777@lid", "abc12025550103@c.us"],
  ]));
  assert.deepEqual(result.map((c) => c.id), ["12025550101@c.us"]);
});

test("dedupe is by actual identity, never by display name", () => {
  const result = filterContacts([
    { id: "12025550101@c.us", name: "Same" },
    { id: "12025550102@c.us", name: "Same" },
    { id: "12025550101@c.us", name: "Alias" },
    { id: "999999@lid", name: "Another alias" },
  ], undefined, new Map([["999999@lid", "12025550101@c.us"]]));
  assert.deepEqual(result.map((c) => c.id), ["12025550101@c.us", "12025550102@c.us"]);
});

test("self LID and phone aliases are excluded together", () => {
  assert.deepEqual(filterContacts([{ id: "12025550101@c.us", name: "Self" }], "999999@lid", new Map([["999999@lid", "12025550101@c.us"]])), []);
});
