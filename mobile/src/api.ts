export interface Session {
  url: string;
  token: string;
  expires_at: string;
}
export interface Person {
  id: string;
  name: string;
  phone: string;
  can_invite_users?: boolean;
}
export interface Party {
  id: string;
  name: string;
}
export interface Report {
  id: string;
  party_name: string;
  as_of: string;
  status: string;
  error: string | null;
  finished_at: string | null;
  details: { pending_amount: string; pages: number } | null;
}
export interface Invoice {
  file_id: string;
  bill_number: string;
  financial_year: string;
  party_name: string;
  date: string;
  file_name: string;
  conflicting_copies: boolean;
}
export function officeUrl(value: string): string {
  const url = new URL(value.trim());
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.pathname !== "/" && url.pathname !== "")
  ) {
    throw new Error(
      "Enter the office HTTPS address provided in Settings. Do not include a path or password.",
    );
  }
  return url.origin;
}
export async function request<T>(
  url: string,
  path: string,
  token?: string,
  body?: unknown,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90000);
  try {
    const response = await fetch(url + "/mobile/v1" + path, {
      method: body === undefined ? "GET" : "POST",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const text = await response.text();
    const incomplete =
      body !== undefined
        ? "The office did not confirm this request. Check its result in Activity, Office requests or Shared tasks before trying again."
        : response.status === 401
          ? "Access expired or was revoked. Ask the office for a new invite."
          : response.status >= 500
            ? "The office service is offline or restarting. Start Office Dashboard on the office PC, then refresh this screen."
            : "The office returned an incomplete response. Refresh this screen; if it continues, check Office Dashboard on the office PC.";
    let data: unknown;
    try {
      data = text.trim() ? JSON.parse(text) : null;
    } catch {
      throw new Error(incomplete);
    }
    if (data === null || typeof data !== "object") throw new Error(incomplete);
    if (!response.ok) {
      if (body !== undefined && response.status >= 500)
        throw new Error(incomplete);
      const detail = "detail" in data ? data.detail : null;
      throw new Error(typeof detail === "string" ? detail : incomplete);
    }
    return data as T;
  } catch (error) {
    if (
      error instanceof Error &&
      /UnknownHostException|Unable to resolve host/i.test(error.message)
    ) {
      throw new Error(
        "Cannot find the office address. Check that Tailscale is connected. If Android Private DNS is enabled, try setting it to Automatic or Off.",
      );
    }
    if (
      error instanceof Error &&
      (error.name === "AbortError" ||
        error.message === "Network request failed")
    ) {
      throw new Error(
        body === undefined
          ? "Cannot reach the office. Check Tailscale and your connection, then refresh this screen."
          : "Connection lost before confirmation. Check the result in Activity, Office requests or Shared tasks before trying again.",
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
export function todayIndia(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  return ["year", "month", "day"]
    .map((key) => parts.find((part) => part.type === key)!.value)
    .join("-");
}
