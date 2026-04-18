import { useRef, useState, useCallback } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Platform,
  Dimensions,
} from "react-native";
import { CameraView, CameraType, useCameraPermissions } from "expo-camera";

/* ── Screen dimensions for explicit sizing ── */
const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get("window");
const CAMERA_HEIGHT = SCREEN_HEIGHT * 0.62;

/* ── Types ── */
export type CaptureResult = {
  uri: string;
  base64?: string;
  width: number;
  height: number;
};

type Props = {
  onCapture: (result: CaptureResult) => void;
  onError: (message: string) => void;
  disabled?: boolean;
};

export default function LivenessCamera({
  onCapture,
  onError,
  disabled = false,
}: Props) {
  const cameraRef = useRef<CameraView>(null);
  const [permission, requestPermission] = useCameraPermissions();
  const [capturing, setCapturing]       = useState(false);
  const [cameraReady, setCameraReady]   = useState(false);
  const [mountError, setMountError]     = useState<string | null>(null);

  /* ── Capture handler ── */
  const handleCapture = useCallback(async () => {
    if (!cameraRef.current || !cameraReady || capturing) return;

    try {
      setCapturing(true);

      const photo = await cameraRef.current.takePictureAsync({
        quality: 0.8,
        base64: true,
        skipProcessing: Platform.OS === "android",
      });

      if (!photo) {
        onError("Camera returned no image. Please try again.");
        return;
      }

      onCapture({
        uri:    photo.uri,
        base64: photo.base64 ?? undefined,
        width:  photo.width,
        height: photo.height,
      });

    } catch (err) {
      console.error("[Camera] capture error:", err);
      onError("Failed to capture image. Please try again.");
    } finally {
      setCapturing(false);
    }
  }, [cameraRef, cameraReady, capturing, onCapture, onError]);

  /* ── Permission: loading ── */
  if (!permission) {
    return (
      <View className="flex-1 items-center justify-center bg-slate-900">
        <ActivityIndicator size="large" color="#3b82f6" />
        <Text className="text-slate-400 text-sm mt-3">
          Checking camera permission…
        </Text>
      </View>
    );
  }

  /* ── Permission: denied ── */
  if (!permission.granted) {
    return (
      <View className="flex-1 items-center justify-center bg-slate-900 px-8">
        <Text className="text-5xl mb-5">📷</Text>
        <Text className="text-white text-xl font-bold text-center mb-3">
          Camera Access Required
        </Text>
        <Text className="text-slate-400 text-sm text-center leading-relaxed mb-8">
          Liveness verification requires camera access to confirm your identity.
          Your images are never stored.
        </Text>
        <TouchableOpacity
          className="bg-blue-600 rounded-2xl px-8 py-4 active:bg-blue-700"
          onPress={requestPermission}
          activeOpacity={0.85}
        >
          <Text className="text-white text-base font-bold">
            Grant Camera Access
          </Text>
        </TouchableOpacity>
      </View>
    );
  }

  /* ── Mount error ── */
  if (mountError) {
    return (
      <View className="flex-1 items-center justify-center bg-slate-900 px-8">
        <Text className="text-5xl mb-5">⚠️</Text>
        <Text className="text-white text-lg font-bold text-center mb-3">
          Camera Failed to Start
        </Text>
        <Text className="text-slate-400 text-sm text-center mb-8">
          {mountError}
        </Text>
        <TouchableOpacity
          className="bg-blue-600 rounded-2xl px-8 py-4"
          onPress={() => setMountError(null)}
          activeOpacity={0.85}
        >
          <Text className="text-white text-base font-bold">Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  /* ── Camera view ── */
  return (
    <View style={{ flex: 1 }}>

      {/* Camera container — explicit pixel dimensions fix Android black screen */}
      <View
        style={{
          marginHorizontal: 16,
          borderRadius: 24,
          overflow: "hidden",
          width: SCREEN_WIDTH - 32,
          height: CAMERA_HEIGHT,
        }}
      >
        {/* ── Live camera feed — explicit size, no flex ── */}
        <CameraView
          ref={cameraRef}
          facing={"front" as CameraType}
          style={{
            width: SCREEN_WIDTH - 32,
            height: CAMERA_HEIGHT,
          }}
          onCameraReady={() => {
            console.log("[Camera] READY");
            setCameraReady(true);
          }}
          onMountError={(e) => {
            console.error("[Camera] MOUNT ERROR:", e);
            setMountError("Camera failed to initialize. Please restart the app.");
          }}
        />

        {/* ── Overlay — sits on top via absolute positioning ── */}
        <View
          style={{
            position: "absolute",
            top: 0, left: 0,
            width: SCREEN_WIDTH - 32,
            height: CAMERA_HEIGHT,
          }}
        >
          {/* Face oval guide */}
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
            <View
              style={{
                width: 210,
                height: 270,
                borderRadius: 105,
                borderWidth: 3,
                borderColor: cameraReady ? "#3b82f6" : "#475569",
                borderStyle: "dashed",
              }}
            />
          </View>

          {/* Corner brackets */}
          <CornerBracket position="top-left"     />
          <CornerBracket position="top-right"    />
          <CornerBracket position="bottom-left"  />
          <CornerBracket position="bottom-right" />

          {/* Status badge */}
          <View style={{ position: "absolute", top: 16, left: 0, right: 0, alignItems: "center" }}>
            {cameraReady ? (
              <View
                style={{
                  backgroundColor: "rgba(0,0,0,0.55)",
                  borderRadius: 999,
                  paddingHorizontal: 16,
                  paddingVertical: 6,
                  flexDirection: "row",
                  alignItems: "center",
                }}
              >
                <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: "#34d399", marginRight: 8 }} />
                <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>
                  Camera Ready
                </Text>
              </View>
            ) : (
              <View
                style={{
                  backgroundColor: "rgba(0,0,0,0.55)",
                  borderRadius: 999,
                  paddingHorizontal: 16,
                  paddingVertical: 6,
                  flexDirection: "row",
                  alignItems: "center",
                }}
              >
                <ActivityIndicator size="small" color="#94a3b8" style={{ marginRight: 6 }} />
                <Text style={{ color: "#94a3b8", fontSize: 12 }}>Starting camera…</Text>
              </View>
            )}
          </View>

        </View>
      </View>

      {/* ── Capture button ── */}
      <View style={{ alignItems: "center", justifyContent: "center", paddingVertical: 28 }}>
        <TouchableOpacity
          onPress={handleCapture}
          disabled={!cameraReady || capturing || disabled}
          activeOpacity={0.8}
        >
          <View
            style={{
              width: 80,
              height: 80,
              borderRadius: 40,
              borderWidth: 4,
              borderColor: cameraReady && !disabled ? "#3b82f6" : "#475569",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {capturing ? (
              <ActivityIndicator size="large" color="#3b82f6" />
            ) : (
              <View
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: 28,
                  backgroundColor: cameraReady && !disabled ? "#2563eb" : "#334155",
                }}
              />
            )}
          </View>
        </TouchableOpacity>

        <Text style={{ color: "#94a3b8", fontSize: 12, marginTop: 10 }}>
          {capturing ? "Capturing…" : "Tap to capture"}
        </Text>
      </View>

    </View>
  );
}

/* ── Corner bracket decorator ── */
type CornerPos = "top-left" | "top-right" | "bottom-left" | "bottom-right";

function CornerBracket({ position }: { position: CornerPos }) {
  const isTop  = position.startsWith("top");
  const isLeft = position.endsWith("left");
  const size   = 26;
  const thick  = 3;
  const offset = 14;

  return (
    <View
      style={{
        position:          "absolute",
        top:               isTop   ? offset : undefined,
        bottom:            !isTop  ? offset : undefined,
        left:              isLeft  ? offset : undefined,
        right:             !isLeft ? offset : undefined,
        width:             size,
        height:            size,
        borderTopWidth:    isTop   ? thick : 0,
        borderBottomWidth: !isTop  ? thick : 0,
        borderLeftWidth:   isLeft  ? thick : 0,
        borderRightWidth:  !isLeft ? thick : 0,
        borderColor:       "#3b82f6",
      }}
    />
  );
}