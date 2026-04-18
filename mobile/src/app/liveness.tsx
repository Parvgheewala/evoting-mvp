import { useState, useCallback } from "react";
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
import LivenessCamera, { type CaptureResult } from "../components/LivenessCamera";

type LivenessStep = "instructions" | "camera" | "preview" | "submitting" | "success" | "error";

export default function LivenessScreen() {
  const router  = useRouter();
  const params  = useLocalSearchParams<{ aadhaarId: string; voterId: string }>();

  const [step, setStep]         = useState<LivenessStep>("instructions");
  const [capture, setCapture]   = useState<CaptureResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

  /* ── Capture success ── */
  const handleCapture = useCallback((result: CaptureResult) => {
    setCapture(result);
    setStep("preview");
  }, []);

  /* ── Capture error ── */
  const handleError = useCallback((message: string) => {
    setErrorMsg(message);
    setStep("error");
  }, []);

  /* ── Submit for verification (placeholder — API in Step 6) ── */
  const handleSubmit = useCallback(async () => {
    if (!capture) return;
    setStep("submitting");

    // Placeholder: simulate backend liveness call
    await new Promise((res) => setTimeout(res, 1800));

    // TODO (Step 6): replace with real API call using capture.base64
    setStep("success");
  }, [capture]);

  /* ── Retake ── */
  const handleRetake = useCallback(() => {
    setCapture(null);
    setErrorMsg("");
    setStep("camera");
  }, []);

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
                <StepDot number={1} state="done" />
                <StepLine filled />
                <StepDot number={2} state="active" />
                <StepLine filled={false} />
                <StepDot number={3} state="idle" />
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
              Position your face in the oval
            </Text>
            <Text className="text-slate-400 text-xs mt-1">
              Keep still and look directly at the camera
            </Text>
          </View>
          <LivenessCamera
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
        <View className="flex-1 px-6 pt-6 pb-10">
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
            <MetaRow label="Resolution" value={`${capture.width} × ${capture.height}`} />
            <MetaRow label="Voter ID" value={params.voterId ?? "—"} />
            <MetaRow label="Aadhaar" value={maskAadhaar(params.aadhaarId ?? "")} last />
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
        </View>
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
  const bg = state === "done" ? "bg-emerald-600" : state === "active" ? "bg-blue-600" : "bg-slate-700";
  return (
    <View className={`w-8 h-8 rounded-full items-center justify-center ${bg}`}>
      <Text className={`text-xs font-bold ${state === "idle" ? "text-slate-500" : "text-white"}`}>
        {state === "done" ? "✓" : number}
      </Text>
    </View>
  );
}

function StepLine({ filled }: { filled: boolean }) {
  return <View className={`flex-1 h-0.5 mx-1 ${filled ? "bg-emerald-600" : "bg-slate-700"}`} />;
}

function MetaRow({ label, value, last = false }: { label: string; value: string; last?: boolean }) {
  return (
    <View className={`flex-row justify-between items-center ${!last ? "mb-3 pb-3 border-b border-slate-700" : ""}`}>
      <Text className="text-slate-400 text-sm">{label}</Text>
      <Text className="text-slate-200 text-sm font-semibold">{value}</Text>
    </View>
  );
}

function maskAadhaar(id: string): string {
  if (id.length !== 12) return id;
  return `XXXX-XXXX-${id.slice(8)}`;
}