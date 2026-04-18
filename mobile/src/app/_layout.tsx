import "../../global.css";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="light" backgroundColor="#0f172a" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: "#0f172a" },
          headerTintColor: "#f8fafc",
          headerTitleStyle: { fontWeight: "700", fontSize: 18 },
          contentStyle: { backgroundColor: "#0f172a" },
          animation: "slide_from_right",
        }}
      >
        <Stack.Screen name="index" options={{ title: "E-Voting MVP", headerShown: true }} />
        <Stack.Screen name="register" options={{ title: "Voter Registration" }} />
        <Stack.Screen name="liveness" options={{ title: "Liveness Check" }} />
        <Stack.Screen name="ballot" options={{ title: "Cast Your Vote" }} />
        <Stack.Screen name="verify" options={{ title: "Verify Vote" }} />
      </Stack>
    </SafeAreaProvider>
  );
}