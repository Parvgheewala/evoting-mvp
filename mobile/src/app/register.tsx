import { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { registerVoter } from "../api/client";

/* ── Validation helpers ── */
const isValidAadhaar = (val: string) => /^\d{12}$/.test(val.trim());
const isValidVoterID = (val: string) => /^[A-Z]{3}\d{7}$/.test(val.trim().toUpperCase());

/* ── Field state type ── */
type FieldState = {
  value: string;
  error: string;
  touched: boolean;
};

const emptyField = (): FieldState => ({ value: "", error: "", touched: false });

export default function RegisterScreen() {
  const router = useRouter();

  const [aadhaar, setAadhaar] = useState<FieldState>(emptyField());
  const [voterID, setVoterID]  = useState<FieldState>(emptyField());
  const [loading, setLoading]  = useState(false);

  /* ── Field change handlers ── */
  function handleAadhaarChange(text: string) {
    const digits = text.replace(/\D/g, "").slice(0, 12);
    setAadhaar({
      value: digits,
      touched: true,
      error: digits.length > 0 && !isValidAadhaar(digits)
        ? "Aadhaar must be exactly 12 digits."
        : "",
    });
  }

  function handleVoterIDChange(text: string) {
    const upper = text.toUpperCase().slice(0, 10);
    setVoterID({
      value: upper,
      touched: true,
      error: upper.length > 0 && !isValidVoterID(upper)
        ? "Format must be 3 letters + 7 digits (e.g. ABC1234567)."
        : "",
    });
  }

  /* ── Submit ── */
  async function handleContinue() {
    const aadhaarOk = isValidAadhaar(aadhaar.value);
    const voterIDOk = isValidVoterID(voterID.value);

    // Force-touch both fields to show errors if untouched
    setAadhaar((prev) => ({
      ...prev,
      touched: true,
      error: aadhaarOk ? "" : "Aadhaar must be exactly 12 digits.",
    }));
    setVoterID((prev) => ({
      ...prev,
      touched: true,
      error: voterIDOk ? "" : "Format must be 3 letters + 7 digits (e.g. ABC1234567).",
    }));

    if (!aadhaarOk || !voterIDOk) return;

    setLoading(true);

    // Simulate brief validation delay before navigating
    try {
      

      const response = await registerVoter({
        aadhaar_id: aadhaar.value,
        voter_id:   voterID.value,
        full_name:  "Voter",   // TODO: add full_name field to register form
      });

      router.push({
        pathname: "/liveness",
        params: {
          aadhaarId:  aadhaar.value,
          voterId:    voterID.value,
          sessionId:  response.liveness_session_id,
          nonce:      response.nonce,
          challenges: JSON.stringify(response.challenges),
        },
      });

    } catch (err: any) {
      setLoading(false);
      // Show inline error — the field error state is reused here
      setAadhaar((prev) => ({
        ...prev,
        error: err?.message ?? "Registration failed. Please try again.",
        touched: true,
      }));
    } finally {
      setLoading(false);
    }

  }

  const formReady =
    isValidAadhaar(aadhaar.value) && isValidVoterID(voterID.value);

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
          <View className="flex-1 px-6 pt-8 pb-10 justify-between">

            {/* ── Top section ── */}
            <View>
              {/* Step indicator */}
              <View className="flex-row items-center mb-8">
                <StepDot number={1} active />
                <StepLine active />
                <StepDot number={2} active={false} />
                <StepLine active={false} />
                <StepDot number={3} active={false} />
              </View>

              {/* Heading */}
              <Text className="text-white text-2xl font-bold mb-1">
                Voter Identity
              </Text>
              <Text className="text-slate-400 text-sm mb-8 leading-relaxed">
                Enter your Aadhaar and Voter ID exactly as printed on your documents.
              </Text>

              {/* Aadhaar field */}
              <InputField
                label="Aadhaar Number"
                placeholder="12-digit Aadhaar"
                value={aadhaar.value}
                onChangeText={handleAadhaarChange}
                error={aadhaar.touched ? aadhaar.error : ""}
                keyboardType="numeric"
                maxLength={12}
                hint="e.g. 234512348765"
              />

              {/* Voter ID field */}
              <InputField
                label="Voter ID"
                placeholder="e.g. ABC1234567"
                value={voterID.value}
                onChangeText={handleVoterIDChange}
                error={voterID.touched ? voterID.error : ""}
                keyboardType="default"
                maxLength={10}
                hint="3 uppercase letters followed by 7 digits"
                autoCapitalize="characters"
              />

              {/* Info notice */}
              <View className="bg-blue-950 border border-blue-800 rounded-xl p-4 mt-2">
                <Text className="text-blue-300 text-xs leading-relaxed">
                  🔒 Your details are encrypted end-to-end and never stored in plain text.
                  Liveness verification follows in the next step.
                </Text>
              </View>
            </View>

            {/* ── Bottom button ── */}
            <View className="mt-10">
              <TouchableOpacity
                className={`w-full rounded-2xl py-4 items-center justify-center
                  ${formReady ? "bg-blue-600 active:bg-blue-700" : "bg-slate-700"}`}
                onPress={handleContinue}
                disabled={loading}
                activeOpacity={0.85}
              >
                {loading ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text
                    className={`text-base font-bold tracking-wide
                      ${formReady ? "text-white" : "text-slate-500"}`}
                  >
                    Continue to Liveness Check →
                  </Text>
                )}
              </TouchableOpacity>

              <TouchableOpacity
                className="mt-4 items-center"
                onPress={() => router.back()}
                activeOpacity={0.7}
              >
                <Text className="text-slate-500 text-sm">← Back to Home</Text>
              </TouchableOpacity>
            </View>

          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

/* ══════════════════════════════════════
   Helper sub-components
══════════════════════════════════════ */

function InputField({
  label,
  placeholder,
  value,
  onChangeText,
  error,
  keyboardType,
  maxLength,
  hint,
  autoCapitalize = "none",
}: {
  label: string;
  placeholder: string;
  value: string;
  onChangeText: (t: string) => void;
  error: string;
  keyboardType: "numeric" | "default";
  maxLength: number;
  hint: string;
  autoCapitalize?: "none" | "characters" | "words" | "sentences";
}) {
  const hasError = error.length > 0;
  const borderColor = hasError ? "border-red-500" : value.length > 0 ? "border-blue-500" : "border-slate-700";

  return (
    <View className="mb-5">
      <Text className="text-slate-300 text-sm font-semibold mb-2">{label}</Text>
      <TextInput
        className={`bg-slate-800 border ${borderColor} rounded-xl px-4 py-3.5
          text-white text-base`}
        placeholder={placeholder}
        placeholderTextColor="#475569"
        value={value}
        onChangeText={onChangeText}
        keyboardType={keyboardType}
        maxLength={maxLength}
        autoCapitalize={autoCapitalize}
        autoCorrect={false}
        autoComplete="off"
        returnKeyType="next"
      />
      {hasError ? (
        <Text className="text-red-400 text-xs mt-1.5 ml-1">⚠ {error}</Text>
      ) : (
        <Text className="text-slate-600 text-xs mt-1.5 ml-1">{hint}</Text>
      )}
    </View>
  );
}

function StepDot({ number, active }: { number: number; active: boolean }) {
  return (
    <View
      className={`w-8 h-8 rounded-full items-center justify-center
        ${active ? "bg-blue-600" : "bg-slate-700"}`}
    >
      <Text className={`text-xs font-bold ${active ? "text-white" : "text-slate-500"}`}>
        {number}
      </Text>
    </View>
  );
}

function StepLine({ active }: { active: boolean }) {
  return (
    <View className={`flex-1 h-0.5 mx-1 ${active ? "bg-blue-600" : "bg-slate-700"}`} />
  );
}