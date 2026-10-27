export type BridgeState =
  | "starting"
  | "qr"
  | "authenticated"
  | "ready"
  | "retrying"
  | "disconnected"
  | "auth_failure"
  | "error";

export interface BridgeContact {
  id: string;
  name: string;
  number?: string;
  is_business?: boolean;
}

export interface BridgeStatus {
  status: BridgeState;
  connected: boolean;
  qr_available: boolean;
  initializing: boolean;
  requires_action: null | "link" | "relink" | "repair";
  message: string | null;
  generation: number;
  qr_revision: number;
}

export interface SendReceipt {
  status: "sent";
  message_id: string;
  operation_id: string;
}
