import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AccessibilityInfo,
  findNodeHandle,
  Keyboard,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { dialogActions, dialogChoice, DialogAction, DialogRequest } from "./dialogModel";

type DialogApi = { alert: (title: string, message?: string, actions?: DialogAction[]) => void };
const Context = createContext<DialogApi | null>(null);

export function useAppDialog() {
  const value = useContext(Context);
  if (!value) throw new Error("App dialogs require AppDialogProvider.");
  return value;
}

export function AppDialogProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<DialogRequest[]>([]);
  const sequence = useRef(0), lastHandled = useRef(0);
  const titleRef = useRef<React.ComponentRef<typeof Text>>(null);
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  const [reduceMotion, setReduceMotion] = useState(false);
  useEffect(() => {
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((value) => {
      if (mounted) setReduceMotion(value);
    });
    const listener = AccessibilityInfo.addEventListener("reduceMotionChanged", setReduceMotion);
    return () => { mounted = false; listener.remove(); };
  }, []);
  const api = useMemo<DialogApi>(() => ({
    alert(title, message = "", actions) {
      Keyboard.dismiss();
      const request = { id: ++sequence.current, title, message, actions: dialogActions(actions) };
      setQueue((old) => [...old, request]);
    },
  }), []);
  const current = queue[0];
  const dismiss = useCallback((request: DialogRequest, index?: number) => {
    // Ignore a second tap before React has removed the dialog.
    if (request.id <= lastHandled.current) return;
    lastHandled.current = request.id;
    setQueue((old) => old.filter((item) => item.id !== request.id));
    dialogChoice(request, index)?.onPress?.();
  }, []);
  return (
    <Context.Provider value={api}>
      {children}
      <Modal visible={!!current} transparent animationType={reduceMotion ? "none" : "fade"}
        statusBarTranslucent onRequestClose={() => current && dismiss(current)}
        onShow={() => {
          const node = findNodeHandle(titleRef.current);
          if (node) AccessibilityInfo.setAccessibilityFocus(node);
        }}>
        {current && (
          <View style={[local.overlay, { paddingTop: insets.top + 24, paddingBottom: insets.bottom + 24 }]}>
            <Pressable style={StyleSheet.absoluteFill} onPress={() => dismiss(current)}
              accessibilityRole="button" accessibilityLabel="Close without making changes" />
            <View accessibilityViewIsModal style={[local.dialog, { maxHeight: height * 0.8 }]}>
              <ScrollView bounces={false} style={{ flexShrink: 1 }} contentContainerStyle={local.content}>
                <Text ref={titleRef} accessibilityRole="header" style={local.title}>{current.title}</Text>
                {!!current.message && <Text style={local.message}>{current.message}</Text>}
              </ScrollView>
              <View style={[local.actions, current.actions.length > 2 && { flexDirection: "column" }]}>
                {current.actions.map((action, index) => (
                  <Pressable key={index} accessibilityRole="button" accessibilityLabel={action.text}
                    onPress={() => dismiss(current, index)} style={({ pressed }) => [
                      local.button,
                      current.actions.length <= 2 && { flex: 1 },
                      index > 0 && (current.actions.length <= 2 ? local.verticalDivider : local.horizontalDivider),
                      pressed && { backgroundColor: "#eeeeee" },
                    ]}>
                    <Text style={[local.buttonText,
                      action.style !== "cancel" && { fontWeight: "600" },
                      action.style === "destructive" && { color: "#d12622" },
                    ]}>{action.text}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </View>
        )}
      </Modal>
    </Context.Provider>
  );
}

const local = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "#00000055", justifyContent: "center", alignItems: "center", paddingHorizontal: 28 },
  dialog: { width: "100%", maxWidth: 320, backgroundColor: "#ffffff", borderRadius: 14, overflow: "hidden" },
  content: { padding: 22, gap: 9 },
  title: { color: "#1c1c1e", fontSize: 18, fontWeight: "600", lineHeight: 24, textAlign: "center" },
  message: { color: "#3a3a3c", fontSize: 14, lineHeight: 21, textAlign: "center" },
  actions: { flexDirection: "row", borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: "#c7c7cc" },
  button: { paddingVertical: 14, paddingHorizontal: 10, minHeight: 50, alignItems: "center", justifyContent: "center" },
  verticalDivider: { borderLeftWidth: StyleSheet.hairlineWidth, borderLeftColor: "#c7c7cc" },
  horizontalDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: "#c7c7cc" },
  buttonText: { color: "#0066cc", fontSize: 16, textAlign: "center", flexShrink: 1 },
});
