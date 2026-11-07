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
import { Icon, palette } from "./ui";

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
    // Ignore a second tap before React has removed the sheet.
    if (request.id <= lastHandled.current) return;
    lastHandled.current = request.id;
    setQueue((old) => old.filter((item) => item.id !== request.id));
    dialogChoice(request, index)?.onPress?.();
  }, []);
  const destructive = current?.actions.some((action) => action.style === "destructive");
  return (
    <Context.Provider value={api}>
      {children}
      <Modal visible={!!current} transparent animationType={reduceMotion ? "none" : "slide"}
        statusBarTranslucent onRequestClose={() => current && dismiss(current)}
        onShow={() => {
          const node = findNodeHandle(titleRef.current);
          if (node) AccessibilityInfo.setAccessibilityFocus(node);
        }}>
        {current && (
          <View style={local.overlay}>
            <Pressable style={StyleSheet.absoluteFill} onPress={() => dismiss(current)}
              accessibilityRole="button" accessibilityLabel="Close without making changes" />
            <View accessibilityViewIsModal style={[local.sheet, {
              maxHeight: height * 0.86, paddingBottom: Math.max(insets.bottom, 20),
            }]}>
              <View style={local.handle} importantForAccessibility="no" />
              <ScrollView bounces={false} contentContainerStyle={local.content}>
                <View style={[local.symbol, destructive && local.dangerSymbol]}>
                  <Icon name={destructive ? "info" : "check"}
                    color={destructive ? "#a23932" : palette.navy} size={26} />
                </View>
                <Text ref={titleRef} accessibilityRole="header" style={local.title}>{current.title}</Text>
                {!!current.message && <Text style={local.message}>{current.message}</Text>}
                <View style={local.actions}>
                  {current.actions.map((action, index) => ({ action, index })).reverse().map(({ action, index }) => (
                    <Pressable key={index} accessibilityRole="button" accessibilityLabel={action.text}
                      onPress={() => dismiss(current, index)} style={({ pressed }) => [
                        local.button,
                        action.style === "cancel" ? local.cancel : action.style === "destructive" ? local.danger : local.primary,
                        pressed && { opacity: 0.8 },
                      ]}>
                      <Text style={[local.buttonText, action.style === "cancel" && local.cancelText]}>{action.text}</Text>
                    </Pressable>
                  ))}
                </View>
              </ScrollView>
            </View>
          </View>
        )}
      </Modal>
    </Context.Provider>
  );
}

const local = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "#122b4366", justifyContent: "flex-end" },
  sheet: { backgroundColor: "#ffffff", borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingTop: 12 },
  handle: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: "#d8e1e8", marginBottom: 22 },
  content: { paddingHorizontal: 24, gap: 16 },
  symbol: { width: 54, height: 54, borderRadius: 27, backgroundColor: palette.light, alignItems: "center", justifyContent: "center" },
  dangerSymbol: { backgroundColor: "#fcece9" },
  title: { color: palette.ink, fontSize: 25, fontWeight: "700", lineHeight: 32 },
  message: { color: palette.muted, fontSize: 16, lineHeight: 25 },
  actions: { gap: 10, marginTop: 8 },
  button: { borderRadius: 18, paddingVertical: 16, paddingHorizontal: 20, minHeight: 54, alignItems: "center", justifyContent: "center" },
  primary: { backgroundColor: palette.navy },
  cancel: { backgroundColor: "#f0f4f7" },
  danger: { backgroundColor: "#a23932" },
  buttonText: { color: "#ffffff", fontSize: 16, fontWeight: "700", textAlign: "center" },
  cancelText: { color: palette.ink },
});
