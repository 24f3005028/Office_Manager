export type SendOutcome = "not_started" | "unknown";

/** Only these fixed, public messages cross the HTTP boundary. Never expose SDK/OS errors. */
export class BridgeError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryable = false,
    readonly outcome: SendOutcome = "not_started",
  ) {
    super(message);
    this.name = "BridgeError";
  }

  json() {
    return { error: this.message, code: this.code, retryable: this.retryable, outcome: this.outcome };
  }
}

export class BridgeNotReadyError extends BridgeError {
  constructor() { super(503, "session_not_ready", "WhatsApp is not ready", true); }
}

export function outcomeUnknown(): BridgeError {
  return new BridgeError(409, "outcome_unknown", "The send outcome is unknown; reconcile it before creating another operation", false, "unknown");
}

export function invalidRequest(message = "Invalid request"): BridgeError {
  return new BridgeError(400, "invalid_request", message);
}
