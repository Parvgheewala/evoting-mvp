import { useEffect, useCallback } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import BallotCard from "../components/BallotCard";
import VIDDisplay from "../components/VIDDisplay";
import {
  useVotingStore,
  MOCK_BALLOT,
  selectBallot,
  selectSelectedCandidate,
  selectHasVoted,
  selectReceipt,
  selectVotingStatus,
  selectVotingError,
} from "../store/votingStore";
import { useAuthStore, selectVoter } from "../store/authStore";

export default function BallotScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ voterId: string }>();

  /* ── Store state ── */
  const status            = useVotingStore(selectVotingStatus);
  const ballot            = useVotingStore(selectBallot);
  const selectedCandidate = useVotingStore(selectSelectedCandidate);
  const hasVoted          = useVotingStore(selectHasVoted);
  const receipt           = useVotingStore(selectReceipt);
  const errorMessage      = useVotingStore(selectVotingError);
  const voter             = useAuthStore(selectVoter);

  const {
    setBallotLoading,
    setBallot,
    selectCandidate,
    clearSelection,
    setSubmitting,
    setSubmitted,
    setError,
  } = useVotingStore();

  /* ── Load ballot on mount ── */
  useEffect(() => {
    if (status !== "idle") return;
      setBallotLoading();
      // Placeholder: simulate fetch — replace with real API in production
      setTimeout(() => {
        setBallot(MOCK_BALLOT);
      }, 800);
    
  }, [status]);

  /* ── Submit vote ── */
  const handleSubmit = useCallback(async () => {
    if (!selectedCandidate) return;
    setSubmitting();

    // Placeholder: simulate backend vote submission
    await new Promise((res) => setTimeout(res, 1500));

    // TODO (Step 6 integration): replace with submitVote() from api/client.ts
    setSubmitted({
      vid:            `VID-${Date.now()}`,
      votedAt:        new Date().toISOString(),
      constituencyId: "central-district",
      receiptHash:    `sha256-${Math.random().toString(36).slice(2, 18)}`,
    });
  }, [selectedCandidate]);

  /* ══════════════════════════════════════
     Render
  ══════════════════════════════════════ */
  return (
    <SafeAreaView className="flex-1 bg-slate-900" edges={["bottom"]}>

      {/* ── LOADING ── */}
      {status === "loading_ballot" && (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator size="large" color="#3b82f6" />
          <Text className="text-slate-400 text-sm mt-4">Loading ballot…</Text>
        </View>
      )}

      {/* ── BALLOT READY ── */}
      {status === "ballot_ready" && (
        <ScrollView
          contentContainerStyle={{ flexGrow: 1 }}
          showsVerticalScrollIndicator={false}
        >
          <View className="px-6 pt-6 pb-10">

            {/* Header */}
            <Text className="text-white text-2xl font-bold mb-1">
              Cast Your Vote
            </Text>
            <Text className="text-slate-400 text-sm mb-2">
              Select one candidate and tap Submit.
            </Text>

            {/* Constituency badge */}
            <View className="bg-slate-800 rounded-full px-4 py-1.5 self-start mb-6 border border-slate-700">
              <Text className="text-slate-300 text-xs font-semibold">
                📍 Central District
              </Text>
            </View>

            {/* Voter ID badge */}
            {(params.voterId || voter?.voterId) && (
              <View className="bg-blue-950 border border-blue-800 rounded-xl px-4 py-3 mb-6">
                <Text className="text-blue-300 text-xs">
                  Voting as:{" "}
                  <Text className="font-bold">
                    {params.voterId ?? voter?.voterId}
                  </Text>
                </Text>
              </View>
            )}

            {/* Candidates */}
            {(ballot || []).map((item) => (
              <BallotCard
                key={item.candidate.id}
                candidate={item.candidate}
                position={item.position}
                selected={selectedCandidate?.id === item.candidate.id}
                disabled={false}
                onSelect={selectCandidate}
              />
            ))}

            {/* Action row */}
            <View className="mt-4 flex-row gap-x-3">
              <TouchableOpacity
                className="flex-1 bg-slate-700 rounded-2xl py-4 items-center border border-slate-600"
                onPress={clearSelection}
                disabled={!selectedCandidate}
                activeOpacity={0.85}
              >
                <Text className={`text-sm font-semibold
                  ${selectedCandidate ? "text-slate-200" : "text-slate-600"}`}>
                  Clear
                </Text>
              </TouchableOpacity>

              <TouchableOpacity
                className={`flex-1 rounded-2xl py-4 items-center
                  ${selectedCandidate ? "bg-blue-600 active:bg-blue-700" : "bg-slate-700"}`}
                onPress={handleSubmit}
                disabled={!selectedCandidate}
                activeOpacity={0.85}
              >
                <Text className={`text-sm font-bold
                  ${selectedCandidate ? "text-white" : "text-slate-500"}`}>
                  Submit Vote →
                </Text>
              </TouchableOpacity>
            </View>

          </View>
        </ScrollView>
      )}

      {/* ── SUBMITTING ── */}
      {status === "submitting" && (
        <View className="flex-1 items-center justify-center px-6">
          <ActivityIndicator size="large" color="#3b82f6" />
          <Text className="text-white text-lg font-semibold mt-6">
            Recording Your Vote…
          </Text>
          <Text className="text-slate-400 text-sm mt-2 text-center">
            Please do not close the app.
          </Text>
        </View>
      )}

      {/* ── SUBMITTED / SUCCESS ── */}
      {status === "submitted" && receipt && (
        <ScrollView
          contentContainerStyle={{ flexGrow: 1 }}
          showsVerticalScrollIndicator={false}
        >
          <View className="flex-1 px-6 pt-8 pb-10 items-center">

            <View className="w-20 h-20 rounded-full bg-emerald-600 items-center justify-center mb-5">
              <Text className="text-4xl">✓</Text>
            </View>

            <Text className="text-white text-2xl font-bold mb-2 text-center">
              Vote Recorded!
            </Text>
            <Text className="text-slate-400 text-sm text-center mb-8 leading-relaxed">
              Your vote has been securely recorded on the ledger.
              Save your VID to verify at any time.
            </Text>

            <VIDDisplay receipt={receipt} />

            <TouchableOpacity
              className="w-full bg-blue-600 rounded-2xl py-4 items-center mt-8 active:bg-blue-700"
              onPress={() => router.push("/verify")}
              activeOpacity={0.85}
            >
              <Text className="text-white text-base font-bold">
                Verify My Vote →
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              className="mt-4"
              onPress={() => router.push("/")}
            >
              <Text className="text-slate-500 text-sm">← Back to Home</Text>
            </TouchableOpacity>

          </View>
        </ScrollView>
      )}

      {/* ── ERROR ── */}
      {status === "error" && (
        <View className="flex-1 items-center justify-center px-6">
          <View className="w-20 h-20 rounded-full bg-red-900 items-center justify-center mb-6">
            <Text className="text-4xl">✕</Text>
          </View>
          <Text className="text-white text-2xl font-bold mb-2">Vote Failed</Text>
          <Text className="text-slate-400 text-sm text-center mb-10 leading-relaxed">
            {errorMessage || "Something went wrong. Please try again."}
          </Text>
          <TouchableOpacity
            className="w-full bg-blue-600 rounded-2xl py-4 items-center active:bg-blue-700"
            onPress={() => setBallot(MOCK_BALLOT)}
            activeOpacity={0.85}
          >
            <Text className="text-white text-base font-bold">Try Again</Text>
          </TouchableOpacity>
        </View>
      )}

    </SafeAreaView>
  );
}