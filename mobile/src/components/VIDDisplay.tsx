import { useState } from "react";
import { View, Text, TouchableOpacity } from "react-native";
import type { VoteReceipt } from "../types";

type Props = {
  receipt: VoteReceipt;
};

export default function VIDDisplay({ receipt }: Props) {
  const [hashVisible, setHashVisible] = useState(false);

  const formattedDate = new Date(receipt.votedAt).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });

  return (
    <View className="w-full bg-slate-800 rounded-2xl border border-slate-700 overflow-hidden">

      {/* Header */}
      <View className="bg-emerald-900 border-b border-emerald-700 px-5 py-3 flex-row items-center">
        <View className="w-2 h-2 rounded-full bg-emerald-400 mr-2" />
        <Text className="text-emerald-300 text-xs font-semibold uppercase tracking-wider">
          Vote Confirmed
        </Text>
      </View>

      <View className="px-5 py-5">

        {/* VID */}
        <View className="mb-5">
          <Text className="text-slate-500 text-xs uppercase tracking-wider mb-1">
            Voter ID Token (VID)
          </Text>
          <View className="bg-slate-900 rounded-xl px-4 py-3 border border-slate-700">
            <Text
              className="text-blue-300 text-base font-mono font-bold tracking-widest"
              selectable
            >
              {receipt.vid}
            </Text>
          </View>
          <Text className="text-slate-600 text-xs mt-1.5">
            Save this token to verify your vote later.
          </Text>
        </View>

        {/* Meta rows */}
        <ReceiptRow label="Voted At"       value={formattedDate} />
        <ReceiptRow label="Constituency"   value={receipt.constituencyId} />

        {/* Receipt hash — toggle visibility */}
        <View className="mt-1">
          <View className="flex-row items-center justify-between mb-1">
            <Text className="text-slate-500 text-xs uppercase tracking-wider">
              Receipt Hash
            </Text>
            <TouchableOpacity onPress={() => setHashVisible((v) => !v)}>
              <Text className="text-blue-400 text-xs font-semibold">
                {hashVisible ? "Hide" : "Show"}
              </Text>
            </TouchableOpacity>
          </View>

          <View className="bg-slate-900 rounded-xl px-4 py-3 border border-slate-700">
            <Text
              className="text-slate-400 text-xs font-mono"
              numberOfLines={hashVisible ? undefined : 1}
              selectable
            >
              {hashVisible ? receipt.receiptHash : "••••••••••••••••••••••••••••••••"}
            </Text>
          </View>
        </View>

      </View>

      {/* Footer */}
      <View className="bg-slate-900 border-t border-slate-700 px-5 py-3">
        <Text className="text-slate-600 text-xs text-center leading-relaxed">
          This receipt is cryptographically signed.{"\n"}
          Use your VID to verify your vote at any time.
        </Text>
      </View>

    </View>
  );
}

/* ── Helper row ── */
function ReceiptRow({ label, value }: { label: string; value: string }) {
  return (
    <View className="flex-row justify-between items-center mb-4">
      <Text className="text-slate-500 text-xs uppercase tracking-wider">{label}</Text>
      <Text className="text-slate-200 text-sm font-semibold">{value}</Text>
    </View>
  );
}