/**
 * Format WhatsApp numbers for people, never for routing.
 *
 * The bridge keeps the original routing id in Contact.id. This helper only
 * formats a verified phone value supplied by the bridge, so an opaque LID can
 * never turn into a made-up phone number in the UI.
 */
export function formatPhoneNumber(value?: string | null): string | null {
  const raw = value?.trim();
  if (!raw) return null;

  const digits = raw.replace(/\D/g, "");
  if (!digits) return raw;

  // Indian E.164 numbers are the primary office contact format. Keep the
  // requested presentation: +91 98030 13891.
  if (digits.length === 12 && digits.startsWith("91")) {
    return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`;
  }

  if (digits.length === 10) {
    return `${digits.slice(0, 5)} ${digits.slice(5)}`;
  }

  if (raw.startsWith("+")) return `+${digits}`;
  return raw;
}

export function searchablePhone(value?: string | null): string {
  return (value ?? "").replace(/\D/g, "");
}
