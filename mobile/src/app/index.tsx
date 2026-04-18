import { View, Text, TouchableOpacity, Image } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuthStore } from "../store/authStore";
import { useVotingStore } from "../store/votingStore";
import { checkHealth } from "../api/client";
import { useEffect, useState } from "react";

export default function HomeScreen() {
  const router = useRouter();

  // ✅ moved inside component (FIX)
  const [apiStatus, setApiStatus] = useState<"checking" | "online" | "offline">("checking");

  // ✅ moved inside component (FIX)
  const authStatus = useAuthStore((s) => s.status);
  const votingStatus = useVotingStore((s) => s.status);

  // ✅ moved inside component (FIX)
  useEffect(() => {
    checkHealth()
      .then(() => setApiStatus("online"))
      .catch(() => setApiStatus("offline"));
  }, []);

  // ✅ still here (unchanged logic)
  console.log("[stores]", { authStatus, votingStatus });

  return (
    <SafeAreaView className="flex-1 bg-slate-900">
      <View className="flex-1 items-center justify-between px-6 py-10">

        {/* Header Badge */}
        <View className="items-center mt-4">
          <View className="bg-blue-600 rounded-full px-4 py-1 mb-6">
            <Text className="text-white text-xs font-semibold tracking-widest uppercase">
              Secure · Transparent · Verified
            </Text>
          </View>

          {/* Title */}
          <Text className="text-white text-4xl font-bold text-center leading-tight">
            E-Voting{"\n"}
            <Text className="text-blue-400">MVP</Text>
          </Text>
          <Text className="text-slate-400 text-sm text-center mt-3 leading-relaxed">
            Cast your vote securely using{"\n"}biometric liveness verification.
          </Text>
        </View>

        {/* Status Card */}
        <View className="w-full bg-slate-800 rounded-2xl p-5 border border-slate-700">
          <Text className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-4">
            System Status
          </Text>

          <StatusRow
            label="Backend API"
            status={
              apiStatus === "checking"
                ? "ready"
                : apiStatus === "online"
                ? "online"
                : "offline"
            }
          />
          <StatusRow
            label="Auth Service"
            status={apiStatus === "online" ? "online" : "offline"}
          />
          <StatusRow
            label="Voting Service"
            status={apiStatus === "online" ? "online" : "offline"}
          />
          <StatusRow
            label="Liveness Check"
            status={apiStatus === "online" ? "ready" : "offline"}
          />
        </View>

        {/* Action Buttons */}
        <View className="w-full gap-y-3">
          <TouchableOpacity
            className="w-full bg-blue-600 rounded-2xl py-4 items-center active:bg-blue-700"
            onPress={() => router.push("/register")}
            activeOpacity={0.85}
          >
            <Text className="text-white text-base font-bold tracking-wide">
              Register to Vote
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            className="w-full bg-slate-700 rounded-2xl py-4 items-center active:bg-slate-600 border border-slate-600"
            onPress={() => router.push("/verify")}
            activeOpacity={0.85}
          >
            <Text className="text-slate-200 text-base font-semibold tracking-wide">
              Verify My Vote
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            className="w-full bg-transparent rounded-2xl py-3 items-center border border-slate-700"
            onPress={() => router.push("/ballot")}
            activeOpacity={0.85}
          >
            <Text className="text-slate-400 text-sm font-medium">
              View Ballot (Demo)
            </Text>
          </TouchableOpacity>
        </View>

      </View>
    </SafeAreaView>
  );
}

/* ── Small helper component ── */
type StatusValue = "online" | "ready" | "offline";

function StatusRow({ label, status }: { label: string; status: StatusValue }) {
  const dotColor: Record<StatusValue, string> = {
    online: "bg-emerald-400",
    ready: "bg-blue-400",
    offline: "bg-red-400",
  };

  const textColor: Record<StatusValue, string> = {
    online: "text-emerald-400",
    ready: "text-blue-400",
    offline: "text-red-400",
  };

  return (
    <View className="flex-row items-center justify-between mb-3">
      <Text className="text-slate-300 text-sm">{label}</Text>
      <View className="flex-row items-center gap-x-2">
        <View className={`w-2 h-2 rounded-full ${dotColor[status]}`} />
        <Text
          className={`text-xs font-semibold capitalize ${textColor[status]}`}
        >
          {status}
        </Text>
      </View>
    </View>
  );
}