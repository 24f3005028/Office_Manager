import { expect, test } from "bun:test";
import { dialogActions, dialogChoice } from "../src/dialogModel";

test("informational sheets have a clear default acknowledgement", () => {
  expect(dialogActions()).toEqual([{ text: "Got it" }]);
  expect(dialogActions([])).toEqual([{ text: "Got it" }]);
});

test("back and backdrop dismissals can only select the cancellation action", () => {
  let writes = 0, cancellations = 0;
  const request = { id: 1, title: "Complete", message: "", actions: [
    { text: "Cancel", style: "cancel", onPress: () => cancellations++ },
    { text: "Mark done", onPress: () => writes++ },
  ] };
  dialogChoice(request)?.onPress?.();
  expect(writes).toBe(0);
  expect(cancellations).toBe(1);
  dialogChoice(request, 1)?.onPress?.();
  expect(writes).toBe(1);
});

test("dismissal never falls back to a destructive action or default confirmation", () => {
  const actions = [{ text: "Disconnect", style: "destructive", onPress: () => { throw Error("unexpected write"); } }];
  const request = { id: 2, title: "Disconnect", message: "", actions };
  expect(dialogChoice(request)).toBeUndefined();
  expect(dialogChoice(request, 9)).toBeUndefined();
  expect(dialogActions(actions)[0].style).toBe("destructive");
  expect(dialogActions(actions)).not.toBe(actions);
});
