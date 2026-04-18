import { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import VIDDisplay from "../components/VIDDisplay";
import { selectReceipt, useVotingStore } from "../store/votingStore";
import type { VoteReceipt } from "../types";

type VerifyStep = "input" | "loading" | "found" | "not_found" | "error";

export default function VerifyScreen() {
  const router  = useRouter();
  const receipt = useVotingStore(selectReceipt);

  const [vid, setVid]           = useState(receipt?.vid ?? "");
  const [step, setStep]         = useState<VerifyStep>("input");
  const [result, setResult]     = useState<VoteReceipt | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

  /* ── Submit VID for lookup ── */
  async function handleVerify() {
    if (vid.trim().length < 6) return;

    setStep("loading");

    // Placeholder: simulate API lookup
    // TODO: replace with verifyVote(vid) from api/client.ts
    await new Promise((res) => setTimeout(res, 1200));

    if (receipt && vid.trim() === receipt.vid) {
      setResult(receipt);
      setStep("found");
    } else {
      setStep("not_found");
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-slate-900" edges={["bottom"]}>
      <KeyboardAvoidingView
        className="flex-1"
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView
          contentContainerStyle={{ flexGrow: 1 }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View className="flex-1 px-6 pt-6 pb-10">

            {/* ── INPUT ── */}
            {(step === "input" || step === "error") && (
              <View className="flex-1 justify-between">
                <View>
                  <Text className="text-white text-2xl font-bold mb-2">
                    Verify Your Vote
                  </Text>
                  <Text className="text-slate-400 text-sm mb-8 leading-relaxed">
                    Enter your Voter ID Token (VID) to confirm your vote was
                    recorded correctly on the ledger.
                  </Text>

                  {/* VID input */}
                  <Text className="text-slate-300 text-sm font-semibold mb-2">
                    Voter ID Token (VID)
                  </Text>
                  <TextInput
                    className="bg-slate-800 border border-slate-700 rounded-xl px-4 py-3.5
                      text-white text-base font-mono"
                    placeholder="e.g. VID-1718000000000"
                    placeholderTextColor="#475569"
                    value={vid}
                    onChangeText={setVid}
                    autoCapitalize="characters"
                    autoCorrect={false}
                    returnKeyType="search"
                    onSubmitEditing={handleVerify}
                  />
                  <Text className="text-slate-600 text-xs mt-1.5 ml-1">
                    Your VID was shown after successfully casting your vote.
                  </Text>

                  {/* Auto-fill hint if receipt exists in store */}
                  {receipt && (
                    <TouchableOpacity
                      className="mt-3 bg-blue-950 border border-blue-800 rounded-xl px-4 py-3"
                      onPress={() => setVid(receipt.vid)}
                    >
                      <Text className="text-blue-300 text-xs">
                        💡 Use your recent VID:{" "}
                        <Text className="font-bold font-mono">{receipt.vid}</Text>
                      </Text>
                    </TouchableOpacity>
                  )}

                  {/* Info box */}
                  <View className="bg-slate-800 border border-slate-700 rounded-xl p-4 mt-6">
                    <Text className="text-slate-300 text-xs font-semibold mb-3 uppercase tracking-wider">
                      How verification works
                    </Text>
                    {HOW_IT_WORKS.map((line, i) => (
                      <View key={i} className="flex-row items-start mb-2">
                        <Text className="text-blue-400 text-xs mr-2 mt-0.5">•</Text>
                        <Text className="text-slate-400 text-xs flex-1 leading-relaxed">
                          {line}
                        </Text>
                      </View>
                    ))}
                  </View>
                </View>

                {/* Submit button */}
                <TouchableOpacity
                  className={`w-full rounded-2xl py-4 items-center mt-8
                    ${vid.trim().length >= 6
                      ? "bg-blue-600 active:bg-blue-700"
                      : "bg-slate-700"}`}
                  onPress={handleVerify}
                  disabled={vid.trim().length < 6}
                  activeOpacity={0.85}
                >
                  <Text
                    className={`text-base font-bold
                      ${vid.trim().length >= 6 ? "text-white" : "text-slate-500"}`}
                  >
                    Verify Vote →
                  </Text>
                </TouchableOpacity>

                <TouchableOpacity
                  className="mt-4 items-center"
                  onPress={() => router.back()}
                >
                  <Text className="text-slate-500 text-sm">← Go Back</Text>
                </TouchableOpacity>
              </View>
            )}

            {/* ── LOADING ── */}
            {step === "loading" && (
              <View className="flex-1 items-center justify-center">
                <ActivityIndicator size="large" color="#3b82f6" />
                <Text className="text-white text-lg font-semibold mt-6">
                  Looking up your vote…
                </Text>
                <Text className="text-slate-400 text-sm mt-2 text-center">
                  Querying the secure ledger
                </Text>
              </View>
            )}

            {/* ── FOUND ── */}
            {step === "found" && result && (
              <View>
                <View className="w-16 h-16 rounded-full bg-emerald-600
                  items-center justify-center mb-5 self-center">
                  <Text className="text-3xl">✓</Text>
                </View>

                <Text className="text-white text-2xl font-bold text-center mb-2">
                  Vote Verified
                </Text>
                <Text className="text-slate-400 text-sm text-center mb-8 leading-relaxed">
                  Your vote is confirmed on the ledger and has not been tampered with.
                </Text>

                <VIDDisplay receipt={result} />

                <TouchableOpacity
                  className="w-full bg-slate-700 rounded-2xl py-4 items-center
                    mt-6 border border-slate-600"
                  onPress={() => {
                    setVid("");
                    setResult(null);
                    setStep("input");
                  }}
                  activeOpacity={0.85}
                >
                  <Text className="text-slate-200 text-sm font-semibold">
                    Verify Another VID
                  </Text>
                </TouchableOpacity>

                <TouchableOpacity
                  className="mt-4 items-center"
                  onPress={() => router.push("/")}
                >
                  <Text className="text-slate-500 text-sm">← Back to Home</Text>
                </TouchableOpacity>
              </View>
            )}

            {/* ── NOT FOUND ── */}
            {step === "not_found" && (
              <View className="flex-1 items-center justify-center">
                <View className="w-20 h-20 rounded-full bg-amber-900
                  items-center justify-center mb-6">
                  <Text className="text-4xl">?</Text>
                </View>
                <Text className="text-white text-2xl font-bold mb-2">
                  VID Not Found
                </Text>
                <Text className="text-slate-400 text-sm text-center mb-10 leading-relaxed">
                  No vote record was found for{"\n"}
                  <Text className="text-white font-mono font-bold">{vid}</Text>
                  {"\n\n"}
                  Double-check your VID and try again.
                </Text>

                <TouchableOpacity
                  className="w-full bg-blue-600 rounded-2xl py-4 items-center
                    active:bg-blue-700"
                  onPress={() => setStep("input")}
                  activeOpacity={0.85}
                >
                  <Text className="text-white text-base font-bold">Try Again</Text>
                </TouchableOpacity>
              </View>
            )}

          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

/* ══════════════════════════════════════
   Constants
══════════════════════════════════════ */
const HOW_IT_WORKS = [
  "Your VID is a unique cryptographic token tied to your vote.",
  "It does not reveal who you voted for — only that your vote exists.",
  "The receipt hash proves your vote has not been altered.",
  "Verification queries a read-only endpoint — nothing is changed.",
];