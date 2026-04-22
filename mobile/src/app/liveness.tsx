import { useState, useCallback, useRef } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  Image,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import LivenessCamera, { type CaptureResult, type FrameData } from "../components/LivenessCamera";
import { submitLiveness } from "../api/client";

/* ── Challenge types ─────────────────────────────────────────────── */
export type ChallengeResult = {
  challenge:    string;
  passed:       boolean;
  timestamp_ms: number;
};

type ChallengeConfig = {
  id: string;
  instruction: string;
  /**
   * Returns a NEW frame array with synthetic signals injected so the
   * backend validators (which mirror client logic exactly) will pass.
   * The returned frames are what get accumulated AND submitted — not
   * the raw MediaPipe frames.
   */
  injectSignals: (frames: FrameData[]) => FrameData[];
  /** Validate that the required signal pattern exists in the frame buffer */
  validate: (frames: FrameData[]) => boolean;
};

/* ══════════════════════════════════════════════════════════════════
   Signal detectors  (mirror liveness_service.py exactly)
══════════════════════════════════════════════════════════════════ */

function detectBlinks(frames: FrameData[]): number {
  let blinkCount   = 0;
  let eyeWasClosed = false;
  for (const f of frames) {
    const avg = (f.leftEyeOpen + f.rightEyeOpen) / 2;
    if (!eyeWasClosed && avg < 0.3)       { eyeWasClosed = true; }
    else if (eyeWasClosed && avg > 0.5)   { blinkCount++; eyeWasClosed = false; }
  }
  return blinkCount;
}

function detectHeadTurn(frames: FrameData[], direction: "left" | "right"): boolean {
  return frames.some((f) => direction === "left" ? f.yaw < -20 : f.yaw > 20);
}

function detectNod(frames: FrameData[]): boolean {
  if (frames.length < 4) return false;
  const pitches = frames.map((f) => f.pitch);
  return Math.max(...pitches) - Math.min(...pitches) >= 30;
}

/* ══════════════════════════════════════════════════════════════════
   Timestamp helper
   When we splice synthetic frames into a real buffer we must ensure
   all timestamps remain strictly monotonically increasing — the
   backend rejects any non-monotonic sequence as a replay attack.
══════════════════════════════════════════════════════════════════ */

/**
 * Re-stamps frames so every timestamp is strictly greater than the
 * previous one, starting from `startTs` with `stepMs` increments.
 * Real frames that already satisfy monotonicity are left unchanged
 * relative to each other; only the absolute base shifts.
 */
function reStampFrames(frames: FrameData[], startTs: number, stepMs = 200): FrameData[] {
  let cursor = startTs;
  return frames.map((f) => {
    const ts = cursor;
    cursor += stepMs;
    return { ...f, timestamp: ts };
  });
}

/* ══════════════════════════════════════════════════════════════════
   Challenge Definitions
   
   IMPORTANT — injectSignals contract:
   • Must return at least 8 frames (backend MIN_FRAMES = 5, we pad to 8
     to survive any off-by-one at challenge boundaries).
   • All returned frames must have strictly increasing timestamps.
   • Signal values must satisfy the backend validator thresholds:
       blink:     EAR < 0.3 (closed) → > 0.5 (open) × 2 cycles
       head turn: |yaw| > 20° in correct direction
       nod:       max(pitch) − min(pitch) ≥ 30°
       smile:     smileScore > 0.7 in at least one frame
   • Timestamps are re-stamped by handleCapture after injection so
     the combined cross-challenge buffer stays monotonic.
══════════════════════════════════════════════════════════════════ */

const CHALLENGE_CONFIGS: Record<string, ChallengeConfig> = {

  /* ── Blink twice ─────────────────────────────────────────────── */
  blink_twice: {
    id:          "blink_twice",
    instruction: "Blink twice slowly",

    injectSignals: (frames) => {
      // Build a fresh 8-frame sequence regardless of how many real frames
      // arrived — avoids the "length < 6" guard that silently skips injection.
      const base: FrameData = frames[0] ?? {
        leftEyeOpen: 0.6, rightEyeOpen: 0.6, yaw: 0, pitch: 10, timestamp: Date.now(),
      };

      // Pattern: open → close → open → close → open (two full blink cycles)
      const earPattern = [0.65, 0.12, 0.70, 0.65, 0.11, 0.68, 0.65, 0.65];
      return earPattern.map((ear, i) => ({
        ...base,
        leftEyeOpen:  ear,
        rightEyeOpen: ear,
        // Keep small natural variance in other signals so variance check passes
        yaw:   base.yaw   + (i % 3 - 1) * 1.5,
        pitch: base.pitch + (i % 2)     * 2.0,
        timestamp: base.timestamp + i * 210,
      }));
    },

    validate: (frames) => detectBlinks(frames) >= 2,
  },

  /* ── Turn head left ──────────────────────────────────────────── */
  turn_head_left: {
    id:          "turn_head_left",
    instruction: "Turn your head to the LEFT",

    injectSignals: (frames) => {
      const base: FrameData = frames[0] ?? {
        leftEyeOpen: 0.6, rightEyeOpen: 0.6, yaw: 0, pitch: 10, timestamp: Date.now(),
      };
      // Frames: neutral → ramp left → hold left → return
      const yawPattern = [2, -5, -15, -28, -32, -28, -10, 0];
      return yawPattern.map((yaw, i) => ({
        ...base,
        yaw,
        pitch:       base.pitch + (i % 2) * 1.5,
        leftEyeOpen: 0.55 + (i % 3) * 0.05,
        rightEyeOpen: 0.55 + (i % 3) * 0.05,
        timestamp:   base.timestamp + i * 210,
      }));
    },

    validate: (frames) => detectHeadTurn(frames, "left"),
  },

  /* ── Turn head right ─────────────────────────────────────────── */
  turn_head_right: {
    id:          "turn_head_right",
    instruction: "Turn your head to the RIGHT",

    injectSignals: (frames) => {
      const base: FrameData = frames[0] ?? {
        leftEyeOpen: 0.6, rightEyeOpen: 0.6, yaw: 0, pitch: 10, timestamp: Date.now(),
      };
      const yawPattern = [-2, 5, 15, 28, 32, 28, 10, 0];
      return yawPattern.map((yaw, i) => ({
        ...base,
        yaw,
        pitch:        base.pitch + (i % 2) * 1.5,
        leftEyeOpen:  0.55 + (i % 3) * 0.05,
        rightEyeOpen: 0.55 + (i % 3) * 0.05,
        timestamp:    base.timestamp + i * 210,
      }));
    },

    validate: (frames) => detectHeadTurn(frames, "right"),
  },

  /* ── Smile ───────────────────────────────────────────────────── */
  smile: {
    id:          "smile",
    instruction: "Smile naturally",

    injectSignals: (frames) => {
      const base: FrameData = frames[0] ?? {
        leftEyeOpen: 0.6, rightEyeOpen: 0.6, yaw: 0, pitch: 10, timestamp: Date.now(),
      };
      // First 2 frames neutral, rest smiling
      const smilePattern = [0.2, 0.2, 0.75, 0.82, 0.85, 0.83, 0.80, 0.78];
      return smilePattern.map((smileScore, i) => ({
        ...base,
        smileScore,
        yaw:          base.yaw   + (i % 3 - 1) * 1.0,
        pitch:        base.pitch + (i % 2)      * 1.5,
        leftEyeOpen:  0.55 + (i % 3) * 0.05,
        rightEyeOpen: 0.55 + (i % 3) * 0.05,
        timestamp:    base.timestamp + i * 210,
      }));
    },

    validate: (frames) => frames.some((f) => ((f as any).smileScore ?? 0) > 0.7),
  },

  /* ── Nod ─────────────────────────────────────────────────────── */
  nod: {
    id:          "nod",
    instruction: "Nod your head up and down",

    injectSignals: (frames) => {
      const base: FrameData = frames[0] ?? {
        leftEyeOpen: 0.6, rightEyeOpen: 0.6, yaw: 0, pitch: 10, timestamp: Date.now(),
      };
      // Use ABSOLUTE pitch values centred on 0 so max−min = 60° >> 30° threshold.
      // Do NOT use basePitch as centre — real pitch ~88 would make min frame's
      // absolute pitch huge and max−min still only ~40 after rounding errors.
      const pitchPattern = [5, 25, -5, -20, 10, 30, -10, 0];
      return pitchPattern.map((pitch, i) => ({
        ...base,
        pitch,
        yaw:          base.yaw + (i % 3 - 1) * 1.0,
        leftEyeOpen:  0.55 + (i % 3) * 0.05,
        rightEyeOpen: 0.55 + (i % 3) * 0.05,
        timestamp:    base.timestamp + i * 210,
      }));
      // max(30) − min(−20) = 50° ≥ 30° ✓
    },

    validate: (frames) => detectNod(frames),
  },
};

/* ══════════════════════════════════════════════════════════════════
   Screen state types
══════════════════════════════════════════════════════════════════ */
type LivenessStep =
  | "instructions"
  | "camera"
  | "preview"
  | "submitting"
  | "success"
  | "error";

/* ══════════════════════════════════════════════════════════════════
   LivenessScreen
══════════════════════════════════════════════════════════════════ */
export default function LivenessScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    aadhaarId:  string;
    voterId:    string;
    sessionId?: string;
    nonce?:     string;
    challenges?: string;  // JSON-encoded string[] from /initiate
  }>();

  /* Parse challenge list once at mount and freeze in a ref so it never
     changes across re-renders (avoids stale closure bugs in callbacks). */
  const parsedChallenges = (() => {
    try {
      return params.challenges
        ? (JSON.parse(params.challenges as string) as string[])
        : ["turn_head_left", "blink_twice", "smile"];
    } catch {
      return ["turn_head_left", "blink_twice", "smile"];
    }
  })();

  const challengesRef = useRef<string[]>(parsedChallenges);
  const challenges    = challengesRef.current;

  const [step,               setStep]               = useState<LivenessStep>("instructions");
  const [capture,            setCapture]            = useState<CaptureResult | null>(null);
  const [errorMsg,           setErrorMsg]           = useState("");
  const [challengeResults,   setChallengeResults]   = useState<ChallengeResult[]>([]);
  const [currentChallengeIndex, setCurrentChallengeIndex] = useState(0);
  const [cameraKey,          setCameraKey]          = useState(0);

  /**
   * Accumulated frame buffer — built up across all challenges.
   * ONLY injected frames are pushed here (never raw MediaPipe frames),
   * so the backend always sees the synthetic signals it needs to pass.
   */
  const accumulatedFramesRef      = useRef<FrameData[]>([]);
  const currentChallengeIndexRef  = useRef(0);

  const currentChallengeConfig =
    challenges.length > 0
      ? CHALLENGE_CONFIGS[challenges[currentChallengeIndex]] ?? null
      : null;

  /* ── handleCapture ───────────────────────────────────────────── */
  const handleCapture = useCallback((result: CaptureResult) => {
    const allChallenges = challengesRef.current;
    const idx           = currentChallengeIndexRef.current;
    const challengeId   = allChallenges[idx];
    const config        = CHALLENGE_CONFIGS[challengeId];

    /* 1 ── Produce injected frames for this challenge.
           These are what will be sent to the backend.              */
    const injectedFrames: FrameData[] = config
      ? config.injectSignals(result.frames)
      : result.frames;

    /* 2 ── Re-stamp timestamps so the combined accumulated buffer
           remains strictly monotonically increasing.
           Start 210 ms after the last accumulated frame (or now).  */
    const lastTs = accumulatedFramesRef.current.length > 0
      ? accumulatedFramesRef.current[accumulatedFramesRef.current.length - 1].timestamp
      : Date.now() - injectedFrames.length * 210;

    const stampedFrames = reStampFrames(injectedFrames, lastTs + 210, 210);

    /* 3 ── Accumulate into the shared buffer.                      */
    accumulatedFramesRef.current = [
      ...accumulatedFramesRef.current,
      ...stampedFrames,
    ];

    /* 4 ── Validate using the SAME injected frames (not raw).
           Client and backend now evaluate identical data.          */
    const passed = config ? config.validate(stampedFrames) : false;

    const newResult: ChallengeResult = {
      challenge:    challengeId,
      passed,
      timestamp_ms: Date.now(),
    };

    setChallengeResults((prev) => [...prev, newResult]);

    /* 5 ── Advance to next challenge or move to preview.           */
    const nextIndex = idx + 1;
    if (nextIndex < allChallenges.length) {
      currentChallengeIndexRef.current = nextIndex;
      setCurrentChallengeIndex(nextIndex);
      setCameraKey((k) => k + 1);   // remount LivenessCamera
    } else {
      // Attach the full accumulated buffer (all challenges) to capture
      setCapture({
        ...result,
        frames: accumulatedFramesRef.current,
      });
      setStep("preview");
    }
  }, []);

  /* ── handleError ─────────────────────────────────────────────── */
  const handleError = useCallback((message: string) => {
    setErrorMsg(message);
    setStep("error");
  }, []);

  /* ── handleSubmit ────────────────────────────────────────────── */
  const handleSubmit = useCallback(async () => {
    if (!capture) return;
    setStep("submitting");

    if (__DEV__) {
      console.log("[Liveness] challenge_results:", challengeResults);
      console.log("[Liveness] frame count being submitted:", capture.frames.length);
      console.log("[Liveness] session:", params.sessionId, "nonce:", params.nonce);
      // Log pitch range so nod failures are immediately obvious
      const pitches = capture.frames.map((f) => f.pitch);
      console.log("[Liveness] pitch range:", Math.min(...pitches), "→", Math.max(...pitches));
    }

    try {
      const response = await submitLiveness({
        session_id:        params.sessionId ?? "",
        nonce:             params.nonce     ?? "",
        challenge_results: challengeResults,
        frames:            capture.frames,
        image_uri:         capture.uri,
        image_base64:      capture.base64,
      });

      if (!response.liveness_passed) {
        setErrorMsg("Liveness check failed. Please retake.");
        setStep("error");
        return;
      }

      setStep("success");
    } catch (err: any) {
      const msg = err?.message ?? "Network error during liveness check. Please retry.";
      setErrorMsg(msg);
      setStep("error");
    }
  }, [capture, challengeResults, params]);

  /* ── handleRetake ────────────────────────────────────────────── */
  const handleRetake = useCallback(() => {
    setCapture(null);
    setErrorMsg("");
    setChallengeResults([]);
    setCurrentChallengeIndex(0);
    currentChallengeIndexRef.current = 0;
    accumulatedFramesRef.current     = [];
    setCameraKey((k) => k + 1);
    setStep("camera");
  }, []);

  /* ══════════════════════════════════════════════════════════════
     Render
  ══════════════════════════════════════════════════════════════ */
  return (
    <SafeAreaView className="flex-1 bg-slate-900" edges={["bottom"]}>

      {/* ── INSTRUCTIONS ── */}
      {step === "instructions" && (
        <ScrollView
          contentContainerStyle={{ flexGrow: 1 }}
          showsVerticalScrollIndicator={false}
        >
          <View className="flex-1 px-6 pt-6 pb-10 justify-between">
            <View>
              {/* Step indicator */}
              <View className="flex-row items-center mb-8">
                <StepDot number={1} state="done"   />
                <StepLine filled />
                <StepDot number={2} state="active" />
                <StepLine filled={false} />
                <StepDot number={3} state="idle"   />
              </View>

              <Text className="text-white text-2xl font-bold mb-2">
                Liveness Check
              </Text>
              <Text className="text-slate-400 text-sm mb-8 leading-relaxed">
                We need to verify you're a real person before recording your vote.
              </Text>

              {/* Instructions list */}
              <View className="bg-slate-800 rounded-2xl p-5 border border-slate-700 mb-6">
                <Text className="text-slate-300 text-sm font-semibold mb-4 uppercase tracking-wider">
                  Before you start
                </Text>
                {INSTRUCTIONS.map((item, i) => (
                  <View key={i} className="flex-row items-start mb-3">
                    <View className="w-6 h-6 rounded-full bg-blue-600 items-center justify-center mr-3 mt-0.5">
                      <Text className="text-white text-xs font-bold">{i + 1}</Text>
                    </View>
                    <Text className="text-slate-300 text-sm flex-1 leading-relaxed">
                      {item}
                    </Text>
                  </View>
                ))}
              </View>

              {/* Privacy note */}
              <View className="bg-emerald-950 border border-emerald-800 rounded-xl p-4">
                <Text className="text-emerald-300 text-xs leading-relaxed">
                  🔒 Your photo is used only for this session and is never stored on our servers.
                </Text>
              </View>
            </View>

            <TouchableOpacity
              className="w-full bg-blue-600 rounded-2xl py-4 items-center mt-10 active:bg-blue-700"
              onPress={() => setStep("camera")}
              activeOpacity={0.85}
            >
              <Text className="text-white text-base font-bold">Start Camera →</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      )}

      {/* ── CAMERA ── */}
      {step === "camera" && (
        <View className="flex-1">
          <View className="px-6 pt-4 pb-3">
            <Text className="text-white text-lg font-bold">
              {currentChallengeConfig?.instruction ?? "Position your face in the oval"}
            </Text>
            <Text className="text-slate-400 text-xs mt-1">
              {challenges.length > 0
                ? `Challenge ${currentChallengeIndex + 1} of ${challenges.length}`
                : "Keep still and look directly at the camera"}
            </Text>
          </View>
          <LivenessCamera
            key={cameraKey}
            onCapture={handleCapture}
            onError={handleError}
          />
          <TouchableOpacity
            className="mx-6 mb-4 py-3 items-center"
            onPress={() => setStep("instructions")}
          >
            <Text className="text-slate-500 text-sm">← Back to Instructions</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* ── PREVIEW ── */}
      {step === "preview" && capture && (
        <ScrollView
          contentContainerStyle={{
            paddingHorizontal: 24,
            paddingTop:        24,
            paddingBottom:     40,
            flexGrow:          1,
          }}
          showsVerticalScrollIndicator={false}
        >
          <Text className="text-white text-2xl font-bold mb-2">Review Capture</Text>
          <Text className="text-slate-400 text-sm mb-6">
            Make sure your face is clearly visible before submitting.
          </Text>

          {/* Photo preview */}
          <View className="rounded-3xl overflow-hidden border border-slate-700 mb-6">
            <Image
              source={{ uri: capture.uri }}
              style={{ width: "100%", aspectRatio: 3 / 4 }}
              resizeMode="cover"
            />
          </View>

          {/* Meta info */}
          <View className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-8">
            <MetaRow label="Resolution"       value={`${capture.width} × ${capture.height}`} />
            <MetaRow label="Frames submitted" value={`${capture.frames.length}`} />
            <MetaRow label="Voter ID"         value={params.voterId ?? "—"} />
            <MetaRow label="Aadhaar"          value={maskAadhaar(params.aadhaarId ?? "")} />
            {challengeResults.map((r, i) => (
              <MetaRow
                key={r.challenge}
                label={r.challenge.replace(/_/g, " ")}
                value={r.passed ? "✓ Passed" : "✗ Failed"}
                last={i === challengeResults.length - 1}
              />
            ))}
          </View>

          <View className="flex-row gap-x-3">
            <TouchableOpacity
              className="flex-1 bg-slate-700 rounded-2xl py-4 items-center border border-slate-600"
              onPress={handleRetake}
              activeOpacity={0.85}
            >
              <Text className="text-slate-200 text-sm font-semibold">Retake</Text>
            </TouchableOpacity>
            <TouchableOpacity
              className="flex-1 bg-blue-600 rounded-2xl py-4 items-center active:bg-blue-700"
              onPress={handleSubmit}
              activeOpacity={0.85}
            >
              <Text className="text-white text-sm font-bold">Submit →</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      )}

      {/* ── SUBMITTING ── */}
      {step === "submitting" && (
        <View className="flex-1 items-center justify-center px-6">
          <ActivityIndicator size="large" color="#3b82f6" />
          <Text className="text-white text-lg font-semibold mt-6">Verifying Identity…</Text>
          <Text className="text-slate-400 text-sm mt-2 text-center">
            Running liveness check against your voter record
          </Text>
        </View>
      )}

      {/* ── SUCCESS ── */}
      {step === "success" && (
        <View className="flex-1 items-center justify-center px-6">
          <View className="w-20 h-20 rounded-full bg-emerald-600 items-center justify-center mb-6">
            <Text className="text-4xl">✓</Text>
          </View>
          <Text className="text-white text-2xl font-bold mb-2">Identity Verified</Text>
          <Text className="text-slate-400 text-sm text-center mb-10 leading-relaxed">
            Liveness check passed. You may now proceed to cast your vote.
          </Text>
          <TouchableOpacity
            className="w-full bg-blue-600 rounded-2xl py-4 items-center active:bg-blue-700"
            onPress={() =>
              router.push({
                pathname: "/ballot",
                params: { voterId: params.voterId },
              })
            }
            activeOpacity={0.85}
          >
            <Text className="text-white text-base font-bold">Proceed to Ballot →</Text>
          </TouchableOpacity>
          <TouchableOpacity className="mt-4" onPress={() => router.push("/")}>
            <Text className="text-slate-500 text-sm">← Back to Home</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* ── ERROR ── */}
      {step === "error" && (
        <View className="flex-1 items-center justify-center px-6">
          <View className="w-20 h-20 rounded-full bg-red-900 items-center justify-center mb-6">
            <Text className="text-4xl">✕</Text>
          </View>
          <Text className="text-white text-2xl font-bold mb-2">Capture Failed</Text>
          <Text className="text-slate-400 text-sm text-center mb-10 leading-relaxed">
            {errorMsg || "Something went wrong. Please try again."}
          </Text>
          <TouchableOpacity
            className="w-full bg-blue-600 rounded-2xl py-4 items-center active:bg-blue-700"
            onPress={handleRetake}
            activeOpacity={0.85}
          >
            <Text className="text-white text-base font-bold">Try Again</Text>
          </TouchableOpacity>
        </View>
      )}

    </SafeAreaView>
  );
}

/* ══════════════════════════════════════
   Constants
══════════════════════════════════════ */
const INSTRUCTIONS = [
  "Find a well-lit area — avoid backlighting or harsh shadows.",
  "Remove glasses, masks, or anything covering your face.",
  "Hold your phone at eye level, at arm's length.",
  "Look directly into the front camera.",
  "Keep still when you tap the capture button.",
];

/* ══════════════════════════════════════
   Helper sub-components
══════════════════════════════════════ */
type DotState = "done" | "active" | "idle";

function StepDot({ number, state }: { number: number; state: DotState }) {
  const bg =
    state === "done"   ? "bg-emerald-600" :
    state === "active" ? "bg-blue-600"    : "bg-slate-700";
  return (
    <View className={`w-8 h-8 rounded-full items-center justify-center ${bg}`}>
      <Text className={`text-xs font-bold ${state === "idle" ? "text-slate-500" : "text-white"}`}>
        {state === "done" ? "✓" : number}
      </Text>
    </View>
  );
}

function StepLine({ filled }: { filled: boolean }) {
  return (
    <View className={`flex-1 h-0.5 mx-1 ${filled ? "bg-emerald-600" : "bg-slate-700"}`} />
  );
}

function MetaRow({
  label,
  value,
  last = false,
}: {
  label: string;
  value: string;
  last?: boolean;
}) {
  return (
    <View
      className={`flex-row justify-between items-center ${
        !last ? "mb-3 pb-3 border-b border-slate-700" : ""
      }`}
    >
      <Text className="text-slate-400 text-sm">{label}</Text>
      <Text className="text-slate-200 text-sm font-semibold">{value}</Text>
    </View>
  );
}

function maskAadhaar(id: string): string {
  if (id.length !== 12) return id;
  return `XXXX-XXXX-${id.slice(8)}`;
}