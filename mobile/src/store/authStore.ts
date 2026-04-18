import { create } from "zustand";

/* ══════════════════════════════════════
   Types
══════════════════════════════════════ */
export type AuthStatus =
  | "idle"
  | "registering"
  | "liveness_pending"
  | "liveness_passed"
  | "liveness_failed"
  | "authenticated"
  | "error";

export type LivenessCapture = {
  uri: string;
  base64?: string;
  width: number;
  height: number;
  capturedAt: string; // ISO timestamp
};

export type Voter = {
  aadhaarId: string;
  voterId: string;
  sessionToken?: string;
  verifiedAt?: string; // ISO timestamp
};

export type AuthState = {
  /* ── State ── */
  status: AuthStatus;
  voter: Voter | null;
  capture: LivenessCapture | null;
  errorMessage: string;

  /* ── Actions ── */
  setRegistering: (aadhaarId: string, voterId: string) => void;
  setLivenessPending: (capture: LivenessCapture) => void;
  setLivenessPassed: (sessionToken: string) => void;
  setLivenessFailed: (reason: string) => void;
  setAuthenticated: (sessionToken: string) => void;
  setError: (message: string) => void;
  reset: () => void;
};

/* ══════════════════════════════════════
   Initial state
══════════════════════════════════════ */
const INITIAL_STATE = {
  status:       "idle" as AuthStatus,
  voter:        null,
  capture:      null,
  errorMessage: "",
};

/* ══════════════════════════════════════
   Store
══════════════════════════════════════ */
export const useAuthStore = create<AuthState>((set, get) => ({
  ...INITIAL_STATE,

  /* ── Step 1: voter fills registration form ── */
  setRegistering(aadhaarId, voterId) {
    set({
      status: "registering",
      voter: { aadhaarId, voterId },
      errorMessage: "",
    });
  },

  /* ── Step 2: photo captured, waiting for API response ── */
  setLivenessPending(capture) {
    set({
      status: "liveness_pending",
      capture: {
        ...capture,
        capturedAt: new Date().toISOString(),
      },
    });
  },

  /* ── Step 3a: liveness API returned success ── */
  setLivenessPassed(sessionToken) {
    const voter = get().voter;
    if (!voter) return;
    set({
      status: "liveness_passed",
      voter: {
        ...voter,
        sessionToken,
        verifiedAt: new Date().toISOString(),
      },
      errorMessage: "",
    });
  },

  /* ── Step 3b: liveness API returned failure ── */
  setLivenessFailed(reason) {
    set({
      status: "liveness_failed",
      errorMessage: reason,
      capture: null,
    });
  },

  /* ── Step 4: voter fully authenticated, ready to vote ── */
  setAuthenticated(sessionToken) {
    const voter = get().voter;
    if (!voter) return;
    set({
      status: "authenticated",
      voter: { ...voter, sessionToken },
      errorMessage: "",
    });
  },

  /* ── Error fallback ── */
  setError(message) {
    set({ status: "error", errorMessage: message });
  },

  /* ── Full reset (logout / start over) ── */
  reset() {
    set(INITIAL_STATE);
  },
}));

/* ══════════════════════════════════════
   Selectors (memoization-friendly)
══════════════════════════════════════ */
export const selectIsAuthenticated = (s: AuthState) =>
  s.status === "authenticated";

export const selectCanVote = (s: AuthState) =>
  s.status === "authenticated" && s.voter?.sessionToken != null;

export const selectVoter = (s: AuthState) => s.voter;

export const selectAuthStatus = (s: AuthState) => s.status;

export const selectAuthError = (s: AuthState) => s.errorMessage;