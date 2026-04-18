import { View, Text, TouchableOpacity } from "react-native";
import type { Candidate } from "../types";

type Props = {
  candidate:  Candidate;
  position:   number;
  selected:   boolean;
  disabled:   boolean;
  onSelect:   (id: string) => void;
};

export default function BallotCard({
  candidate,
  position,
  selected,
  disabled,
  onSelect,
}: Props) {
  const borderColor = selected
    ? "border-blue-500"
    : "border-slate-700";

  const bgColor = selected
    ? "bg-blue-950"
    : "bg-slate-800";

  return (
    <TouchableOpacity
      className={`w-full rounded-2xl border-2 ${borderColor} ${bgColor} p-4 mb-3`}
      onPress={() => !disabled && onSelect(candidate.id)}
      disabled={disabled}
      activeOpacity={0.8}
    >
      <View className="flex-row items-center">

        {/* Position number */}
        <View className="w-8 h-8 rounded-full bg-slate-700 items-center justify-center mr-3">
          <Text className="text-slate-300 text-xs font-bold">{position}</Text>
        </View>

        {/* Party symbol */}
        <View className="w-12 h-12 rounded-xl bg-slate-700 items-center justify-center mr-4">
          <Text className="text-2xl">{candidate.partySymbol}</Text>
        </View>

        {/* Candidate info */}
        <View className="flex-1">
          <Text className="text-white text-base font-bold" numberOfLines={1}>
            {candidate.name}
          </Text>
          <Text className="text-slate-400 text-xs mt-0.5" numberOfLines={1}>
            {candidate.party}
          </Text>
          <Text className="text-slate-600 text-xs mt-0.5" numberOfLines={1}>
            {candidate.constituency}
          </Text>
        </View>

        {/* Selection indicator */}
        <View
          className={`w-6 h-6 rounded-full border-2 items-center justify-center ml-2
            ${selected ? "border-blue-500 bg-blue-500" : "border-slate-600 bg-transparent"}`}
        >
          {selected && (
            <Text className="text-white text-xs font-bold">✓</Text>
          )}
        </View>

      </View>

      {/* Selected banner */}
      {selected && (
        <View className="mt-3 pt-3 border-t border-blue-800">
          <Text className="text-blue-400 text-xs font-semibold text-center tracking-wide uppercase">
            ✓ Selected — tap Submit to confirm
          </Text>
        </View>
      )}
    </TouchableOpacity>
  );
}