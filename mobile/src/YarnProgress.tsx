import { useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  Animated,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from "react-native";

/** An indeterminate thread travelling along a bar; never invents a percentage. */
export default function YarnProgress({
  label = "Working…",
  color = "#315f94",
  style,
  accessibilityLabel,
}: {
  label?: string;
  color?: string;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const travel = useRef(new Animated.Value(0)).current;
  const [width, setWidth] = useState(240);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((value) => {
      if (mounted) setReducedMotion(value);
    });
    const listener = AccessibilityInfo.addEventListener(
      "reduceMotionChanged", setReducedMotion,
    );
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => { mounted = false; listener.remove(); clearInterval(timer); };
  }, []);
  useEffect(() => {
    travel.setValue(0);
    if (reducedMotion) return;
    const animation = Animated.loop(Animated.timing(travel, {
      toValue: 1, duration: 2100, useNativeDriver: true, isInteraction: false,
    }));
    animation.start();
    return () => animation.stop();
  }, [travel, reducedMotion]);
  return (
    <View style={[local.container, style]} accessibilityRole="progressbar"
      accessibilityLabel={accessibilityLabel ?? label} accessibilityState={{ busy: true }}>
      <View style={local.track} onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
        <View style={local.baseline} />
        <Animated.View style={[local.thread, { backgroundColor: color, transform: [{
          translateX: reducedMotion ? width / 3 : travel.interpolate({ inputRange: [0, 1], outputRange: [-76, width] }),
        }] }]}>
          {Array.from({ length: 9 }, (_, index) => (
            <View key={index} style={[local.strand, { left: index * 10 }]} />
          ))}
        </Animated.View>
      </View>
      <Text style={local.label}>{label}{seconds >= 5 ? ` · ${seconds}s elapsed` : ""}</Text>
    </View>
  );
}

const local = StyleSheet.create({
  container: { alignSelf: "stretch", minWidth: 120, paddingVertical: 10, gap: 7 },
  track: { height: 10, overflow: "hidden", borderRadius: 5, backgroundColor: "#e3e9ec" },
  baseline: { position: "absolute", top: 4, left: 0, right: 0, height: 2, backgroundColor: "#c5d4e1" },
  thread: { position: "absolute", width: 76, height: 10, borderRadius: 5, overflow: "hidden" },
  strand: { position: "absolute", top: -5, width: 2, height: 22, backgroundColor: "#ffffff99", transform: [{ rotate: "35deg" }] },
  label: { fontSize: 12, color: "#586b7f", textAlign: "center" },
});
