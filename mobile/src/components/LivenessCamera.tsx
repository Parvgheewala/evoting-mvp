import { useRef, useState, useCallback, useEffect } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Platform,
  Dimensions,
} from "react-native";
import { CameraView, CameraType, useCameraPermissions } from "expo-camera"; 
import * as FaceDetector from "expo-face-detector";
import { isValidFrame } from "../utils/faceSignals";
import { WebView, WebViewMessageEvent } from "react-native-webview";
import { CameraCapturedPicture } from "expo-camera";

const FACE_PROCESSOR = require("../mediapipe/FaceProcessor.html");

/* ── Screen dimensions for explicit sizing ── */
const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get("window");
const CAMERA_HEIGHT = SCREEN_HEIGHT * 0.62;

/* ── Types ── */

/**
 * Per-frame facial signal data captured during liveness.
 * In production: populated by MediaPipe Face Mesh landmarks.
 * In MVP: estimated values that follow the correct schema for backend validation.
 */

type CameraPhoto = {
  uri: string;
  width: number;
  height: number;
  base64?: string;
};
export type FrameData = {
  leftEyeOpen:  number;
  rightEyeOpen: number;
  yaw:          number;
  pitch:        number;
  smileScore?:  number;   // real value from MediaPipe lip corner distance
  timestamp:    number;
};

export type CaptureResult = {
  uri: string;
  base64?: string;
  width: number;
  height: number;
  frames: FrameData[];   // 5–10 frames captured during the session
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
  const frameBufferRef   = useRef<FrameData[]>([]);   // accumulated frames
  const webViewRef       = useRef<WebView>(null);

  const [permission, requestPermission] = useCameraPermissions();
  const [capturing, setCapturing]       = useState(false);
  const [cameraReady, setCameraReady]   = useState(false);
  const [mountError, setMountError]     = useState<string | null>(null);
  const [webViewError, setWebViewError] = useState<string | null>(null);
  const [frameCount, setFrameCount]     = useState(0);
  const [faceMeshReady, setFaceMeshReady] = useState(false);
  const [faceDetected, setFaceDetected]   = useState(false);
  const [liveSignal, setLiveSignal]       = useState<FrameData | null>(null);
    

  /* ── STEP 3 + 4: WebView message handler with 5 FPS throttle ── */
  const lastFrameTimeRef = useRef(0);
  const captureIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const pushFrame = useCallback((frame: FrameData) => {
    const buffer = frameBufferRef.current;
    if (buffer.length >= 10) {
      buffer.shift();
    }
    buffer.push(frame);
    setFrameCount(buffer.length);

    // TASK 1 — signal logging every frame in dev
    if (__DEV__) {
      console.log(
        `[Liveness] #${buffer.length}` +
        ` EAR L:${frame.leftEyeOpen.toFixed(3)} R:${frame.rightEyeOpen.toFixed(3)}` +
        ` | yaw:${frame.yaw.toFixed(1)}` +
        ` | pitch:${frame.pitch.toFixed(1)}` +
        ` | smile:${(frame.smileScore ?? 0).toFixed(3)}` +
        ` | ts:${frame.timestamp}`
      );
    }

    // update live signal for debug overlay (TASK 3)
    setLiveSignal(frame);
  }, []);

  const handleWebViewMessage = useCallback((event: WebViewMessageEvent) => {
    try {
      const data = JSON.parse(event.nativeEvent.data);

      if (data.type === "READY") {
        console.log("[FaceProcessor] MediaPipe loaded and ready");
        setFaceMeshReady(true);
        return;
      }

      if (data.type === "NO_FACE") {
        setFaceDetected(false);
        if (__DEV__) console.log("[FaceProcessor] NO_FACE — buffer paused");
        return;
      }

      if (data.type === "ERROR") {
        setFaceDetected(false);
        console.warn("[FaceProcessor] ERROR:", data.code, data.message ?? "");
        // Only surface fatal errors (camera denied) as hard error state
        if (data.code === "CAMERA_DENIED" || data.code === "FACEMESH_INIT_FAILED") {
          setWebViewError(data.message ?? "Face processor failed");
        }
        return;
      }

      if (data.type !== "FRAME") return;

      // 5 FPS throttle on the RN side as a second guard
      const now = Date.now();
      if (now - lastFrameTimeRef.current < 200) return;
      lastFrameTimeRef.current = now;

      // data.frame is already a computed FrameData from the HTML engine
      const frame = data.frame;
      if (!frame || !isValidFrame(frame)) {
        if (__DEV__) console.warn("[FaceProcessor] invalid frame rejected:", frame);
        return;
      }

      setFaceDetected(true);
      pushFrame(frame);


    } catch (err) {
      console.warn("[FaceProcessor] message parse error:", err);
    }
  }, [pushFrame]);

  

const stopFrameSampling = useCallback(() => {
    if (captureIntervalRef.current) {
      clearInterval(captureIntervalRef.current);
      captureIntervalRef.current = null;
    }
    webViewRef.current?.injectJavaScript(
      `window.dispatchEvent(new MessageEvent('message',{ data: JSON.stringify({ type:'PAUSE' }) })); true;`
    );
  }, []);

  const startFrameCapture = useCallback(() => {
    if (captureIntervalRef.current) return; // already running

    captureIntervalRef.current = setInterval(async () => {
      if (!cameraRef.current || !webViewRef.current) return;

      try {
        const photo = await cameraRef.current.takePictureAsync({
          quality:        0.4,          // low quality — inference only
          base64:         true,
          skipProcessing: true,         // fastest path on Android
          shutterSound:   false,
        });

        if (!photo?.base64) return;

        const dataUrl = `data:image/jpeg;base64,${photo.base64}`;

        // Send frame to WebView for MediaPipe inference
        const escaped = dataUrl.replace(/'/g, "\\'");
        webViewRef.current.injectJavaScript(
          `window.dispatchEvent(new MessageEvent('message',{` +
          `data: JSON.stringify({ type:'FRAME', data:'${escaped}' })` +
          `})); true;`
        );

      } catch (err) {
        if (__DEV__) console.warn("[startFrameCapture] capture error:", err);
      }
    }, 200); // 200ms = 5 FPS
  }, []);


  /* ── Cleanup on unmount ── */
useEffect(() => {
    return () => {
      stopFrameSampling();
    };
  }, [stopFrameSampling]);


/* ── Capture handler ── */
  const handleCapture = useCallback(async () => {
    if (!cameraRef.current || !cameraReady || capturing) return;

    try {
      setCapturing(true);
      stopFrameSampling();

      const photo = await cameraRef.current.takePictureAsync({
        quality: 0.8,
        base64: true,
        skipProcessing: Platform.OS === "android",
      }) as CameraCapturedPicture;

      if (!photo) {
        onError("Camera returned no image. Please try again.");
        return;
      }

      // Ensure we have at least 5 frames; pad with current snapshot if needed
      const frames = [...frameBufferRef.current];

      if (frames.length < 5) {
        onError(
          `Not enough face data yet (${frames.length}/5 frames). ` +
          "Hold still for a moment and try again."
        );
        return;
      }


      onCapture({
        uri:    photo.uri,
        base64: photo.base64 ?? undefined,
        width:  photo.width,
        height: photo.height,
        frames,                    // ← NEW: attach frame signal array
      });

    } catch (err) {
      console.error("[Camera] capture error:", err);
      onError("Failed to capture image. Please try again.");
    } finally {
      setCapturing(false);
    }
  }, [cameraRef, cameraReady, capturing, onCapture, onError, stopFrameSampling]);

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

  /* ── STEP 8: WebView / FaceProcessor error ── */
  if (webViewError) {
    return (
      <View className="flex-1 items-center justify-center bg-slate-900 px-8">
        <Text className="text-5xl mb-5">🧠</Text>
        <Text className="text-white text-lg font-bold text-center mb-3">
          Face Processor Failed
        </Text>
        <Text className="text-slate-400 text-sm text-center mb-8">
          {webViewError}
        </Text>
        <TouchableOpacity
          className="bg-blue-600 rounded-2xl px-8 py-4"
          onPress={() => setWebViewError(null)}
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
            console.log("[Camera] CameraView ready — starting frame capture");
            setCameraReady(true);
            startFrameCapture();

          }}
          onMountError={(e) => {
            console.error("[Camera] MOUNT ERROR:", e);
            setMountError("Camera failed to initialize. Please restart the app.");
          }}
        />

        {/* ── STEP 9: Hidden MediaPipe WebView — inference only ── */}
        <WebView
          ref={webViewRef}
          source={FACE_PROCESSOR}
          style={{
            position: "absolute",
            top: 0, left: 0,
            width: 1, height: 1,   // 1×1 — invisible but mounted
            opacity: 0,
            pointerEvents: "none",
          }}
          onMessage={handleWebViewMessage}
          onError={(e) => {
            const msg = e.nativeEvent.description ?? "WebView failed to load";
            console.error("[FaceProcessor] WebView error:", msg);
            setWebViewError(msg);
          }}
          mediaPlaybackRequiresUserAction={false}
          allowsInlineMediaPlayback
          javaScriptEnabled
          originWhitelist={["*"]}
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
                  {!faceMeshReady
                    ? "Loading FaceMesh…"
                    : frameCount < 5
                    ? `Scanning… (${frameCount}/5)`
                    : `Ready · ${frameCount} frames`}
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

          {/* TASK 3 — debug signal overlay (DEV only) */}
          {__DEV__ && liveSignal && (
            <View
              style={{
                position: "absolute",
                bottom: 12,
                left: 12,
                right: 12,
                backgroundColor: "rgba(0,0,0,0.72)",
                borderRadius: 10,
                padding: 10,
              }}
            >
              {/* Face presence indicator */}
              <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 6 }}>
                <View
                  style={{
                    width: 8, height: 8, borderRadius: 4, marginRight: 6,
                    backgroundColor: faceDetected ? "#34d399" : "#f87171",
                  }}
                />
                <Text style={{ color: "#fff", fontSize: 10, fontWeight: "700", letterSpacing: 1 }}>
                  {faceDetected ? "FACE DETECTED" : "NO FACE"}
                </Text>
                <Text style={{ color: "#64748b", fontSize: 10, marginLeft: "auto" }}>
                  {frameCount} frames
                </Text>
              </View>

              {/* EAR row */}
              <SignalRow
                label="EAR"
                left={liveSignal.leftEyeOpen}
                right={liveSignal.rightEyeOpen}
                threshold={0.3}
                thresholdLabel="blink<0.3"
                formatVal={(v) => v.toFixed(3)}
                warnBelow
              />

              {/* Yaw row */}
              <SignalRow
                label="YAW"
                single={liveSignal.yaw}
                threshold={20}
                thresholdLabel="|yaw|>20"
                formatVal={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}°`}
                warnAboveAbs
              />

              {/* Pitch row */}
              <SignalRow
                label="PITCH"
                single={liveSignal.pitch}
                threshold={15}
                thresholdLabel="|pitch|>15"
                formatVal={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}°`}
                warnAboveAbs
              />

              {/* Smile row */}
              <SignalRow
                label="SMILE"
                single={liveSignal.smileScore ?? 0}
                threshold={0.7}
                thresholdLabel=">0.7"
                formatVal={(v) => v.toFixed(3)}
                warnAbove
              />
            </View>
          )}

        </View>
      </View>

      {/* ── Capture button ── */}
      <View style={{ alignItems: "center", justifyContent: "center", paddingVertical: 28 }}>
        <TouchableOpacity
          onPress={handleCapture}
          disabled={!cameraReady || !faceMeshReady || capturing || disabled || frameCount < 5}
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

/* ── Debug signal row (DEV only) ── */
type SignalRowProps = {
  label:        string;
  formatVal:    (v: number) => string;
  threshold:    number;
  thresholdLabel: string;
  left?:        number;   // for L/R pairs (EAR)
  right?:       number;
  single?:      number;   // for single-value signals
  warnBelow?:   boolean;  // warn when value < threshold (blink)
  warnAbove?:   boolean;  // warn when value > threshold (smile)
  warnAboveAbs?: boolean; // warn when |value| > threshold (yaw/pitch)
};

function SignalRow({
  label, formatVal, threshold, thresholdLabel,
  left, right, single,
  warnBelow, warnAbove, warnAboveAbs,
}: SignalRowProps) {
  const isActive = (v: number) => {
    if (warnBelow)    return v < threshold;
    if (warnAbove)    return v > threshold;
    if (warnAboveAbs) return Math.abs(v) > threshold;
    return false;
  };

  const valueColor = (v: number) => isActive(v) ? "#34d399" : "#94a3b8";

  return (
    <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 3 }}>
      <Text style={{ color: "#64748b", fontSize: 9, width: 38, fontWeight: "600" }}>
        {label}
      </Text>

      {/* L/R pair (EAR) */}
      {left !== undefined && right !== undefined && (
        <>
          <Text style={{ color: valueColor(left),  fontSize: 9, width: 44 }}>
            L:{formatVal(left)}
          </Text>
          <Text style={{ color: valueColor(right), fontSize: 9, width: 44 }}>
            R:{formatVal(right)}
          </Text>
        </>
      )}

      {/* Single value */}
      {single !== undefined && (
        <Text style={{ color: valueColor(single), fontSize: 9, width: 56 }}>
          {formatVal(single)}
        </Text>
      )}

      {/* Threshold label */}
      <Text style={{ color: "#334155", fontSize: 8, marginLeft: "auto" }}>
        {thresholdLabel}
      </Text>
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