export type DialogAction = {
  text: string;
  style?: "default" | "cancel" | "destructive";
  onPress?: () => void;
};
export type DialogRequest = {
  id: number;
  title: string;
  message: string;
  actions: DialogAction[];
};

export function dialogActions(actions?: DialogAction[]): DialogAction[] {
  return actions?.length ? [...actions] : [{ text: "Got it" }];
}

/** Back/outside dismissal can only cancel, never approve an operation. */
export function dialogChoice(request: DialogRequest, index?: number) {
  return index === undefined
    ? request.actions.find((action) => action.style === "cancel")
    : request.actions[index];
}
