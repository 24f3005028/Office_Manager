import type { BridgeContact } from "./types.js";

export interface RawContact {
  id?: { _serialized?: string } | string;
  name?: string;
  pushname?: string;
  shortName?: string;
  number?: string;
  isMyContact?: boolean;
  isGroup?: boolean;
  isMe?: boolean;
  isBusiness?: boolean;
}

// Validate the complete routing identity. Never strip letters or substitute an
// unverified `number` field. A LID is opaque and is only routable after SDK mapping.
export const isPhoneId = (id: string): boolean => /^[1-9]\d{6,14}@c\.us$/.test(id);
export const isLid = (id: string): boolean => /^[A-Za-z0-9._-]{1,50}@lid$/.test(id);
export const isRoutingId = (id: string): boolean => isPhoneId(id) || isLid(id);

export function serializedId(contact: RawContact): string {
  return typeof contact.id === "string" ? contact.id : contact.id?._serialized ?? "";
}

export function savedName(contact: RawContact): string {
  if (contact.isMyContact === false) return "";
  // Preserve the bridge's saved-contact policy: WhatsApp may expose the saved
  // label as name, pushname, or shortName depending on the contact record.
  return contact.name?.trim() || contact.pushname?.trim() || contact.shortName?.trim() || "";
}

export function filterContacts(
  rawContacts: RawContact[], selfId?: string, lidToPhone: ReadonlyMap<string, string> = new Map(),
): BridgeContact[] {
  const selfPhone = selfId && (isPhoneId(selfId) ? selfId : lidToPhone.get(selfId));
  const byIdentity = new Map<string, BridgeContact>();
  for (const contact of rawContacts) {
    const id = serializedId(contact);
    const phoneId = isPhoneId(id) ? id : isLid(id) ? lidToPhone.get(id) : undefined;
    const name = savedName(contact);
    if (!phoneId || !isPhoneId(phoneId) || contact.isGroup || contact.isMe || id === selfId || phoneId === selfPhone) continue;
    if (!name || !/\p{L}/u.test(name)) continue;
    if (byIdentity.has(phoneId)) continue;
    byIdentity.set(phoneId, {
      id: phoneId, name, number: phoneId.slice(0, -5),
      ...(contact.isBusiness ? { is_business: true } : {}),
    });
  }
  return [...byIdentity.values()].sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}
