import { create } from "zustand";

/* ══════════════════════════════════════
   Types
══════════════════════════════════════ */
export type VotingStatus =
  | "idle"
  | "loading_ballot"
  | "ballot_ready"
  | "submitting"
  | "submitted"
  | "error";

export type Candidate = {
  id: string;
  name: string;
  party: string;
  partySymbol: string;   // emoji or icon identifier
  constituency: string;
};

export type BallotItem = {
  candidate: Candidate;
  position: number;
};

export type VoteReceipt = {
  vid: string;           // Voter ID token returned by backend
  votedAt: string;       // ISO timestamp
  constituencyId: string;
  receiptHash: string;   // verification hash
};

export type VotingState = {
  /* ── State ── */
  status: VotingStatus;
  ballot: BallotItem[];
  selectedCandidateId: string | null;
  receipt: VoteReceipt | null;
  errorMessage: string;

  /* ── Actions ── */
  setBallotLoading: () => void;
  setBallot: (items: BallotItem[]) => void;
  selectCandidate: (candidateId: string) => void;
  clearSelection: () => void;
  setSubmitting: () => void;
  setSubmitted: (receipt: VoteReceipt) => void;
  setError: (message: string) => void;
  reset: () => void;
};

/* ══════════════════════════════════════
   Mock ballot (placeholder until API)
══════════════════════════════════════ */
export const MOCK_BALLOT: BallotItem[] = [
  {
    position: 1,
    candidate: {
      id: "cand_001",
      name: "Arjun Mehta",
      party: "National Progress Party",
      partySymbol: "🌾",
      constituency: "Central District",
    },
  },
  {
    position: 2,
    candidate: {
      id: "cand_002",
      name: "Priya Nair",
      party: "United Democratic Front",
      partySymbol: "✋",
      constituency: "Central District",
    },
  },
  {
    position: 3,
    candidate: {
      id: "cand_003",
      name: "Rajesh Kumar",
      party: "People's Alliance",
      partySymbol: "⚙️",
      constituency: "Central District",
    },
  },
  {
    position: 4,
    candidate: {
      id: "cand_004",
      name: "Sunita Rao",
      party: "Green Future Party",
      partySymbol: "🌿",
      constituency: "Central District",
    },
  },
];

/* ══════════════════════════════════════
   Initial state
══════════════════════════════════════ */
const INITIAL_STATE = {
  status:              "idle" as VotingStatus,
  ballot:              [] as BallotItem[],
  selectedCandidateId: null,
  receipt:             null,
  errorMessage:        "",
};

/* ══════════════════════════════════════
   Store
══════════════════════════════════════ */
export const useVotingStore = create<VotingState>((set, get) => ({
  ...INITIAL_STATE,

  /* ── Fetching ballot from API ── */
  setBallotLoading() {
    set({ status: "loading_ballot", ballot: [], selectedCandidateId: null });
  },

  /* ── Ballot received ── */
  setBallot(items) {
    const sorted = [...items].sort((a, b) => a.position - b.position);
    set({ status: "ballot_ready", ballot: sorted, errorMessage: "" });
  },

  /* ── Voter taps a candidate ── */
  selectCandidate(candidateId) {
    const { ballot } = get();
    const exists = ballot.some((b) => b.candidate.id === candidateId);
    if (!exists) return;
    set({ selectedCandidateId: candidateId });
  },

  /* ── Voter deselects ── */
  clearSelection() {
    set({ selectedCandidateId: null });
  },

  /* ── Vote being submitted to API ── */
  setSubmitting() {
    set({ status: "submitting" });
  },

  /* ── Vote confirmed by backend ── */
  setSubmitted(receipt) {
    set({
      status: "submitted",
      receipt,
      selectedCandidateId: null,
      errorMessage: "",
    });
  },

  /* ── Error ── */
  setError(message) {
    set({ status: "error", errorMessage: message });
  },

  /* ── Full reset ── */
  reset() {
    set(INITIAL_STATE);
  },
}));

/* ══════════════════════════════════════
   Selectors
══════════════════════════════════════ */
export const selectBallot = (s: VotingState) => s.ballot;

export const selectSelectedCandidate = (s: VotingState) =>
  s.ballot.find((b) => b.candidate.id === s.selectedCandidateId)?.candidate ?? null;

export const selectHasVoted = (s: VotingState) => s.status === "submitted";

export const selectReceipt = (s: VotingState) => s.receipt;

export const selectVotingStatus = (s: VotingState) => s.status;

export const selectVotingError = (s: VotingState) => s.errorMessage;