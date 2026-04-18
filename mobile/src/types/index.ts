/* ══════════════════════════════════════
   Auth
══════════════════════════════════════ */
export type AuthStatus =
  | "idle"
  | "registering"
  | "liveness_pending"
  | "liveness_passed"
  | "liveness_failed"
  | "authenticated"
  | "error";

export type Voter = {
  aadhaarId:     string;
  voterId:       string;
  sessionToken?: string;
  verifiedAt?:   string;
};

export type LivenessCapture = {
  uri:         string;
  base64?:     string;
  width:       number;
  height:      number;
  capturedAt:  string;
};

/* ══════════════════════════════════════
   Ballot & Voting
══════════════════════════════════════ */
export type Candidate = {
  id:           string;
  name:         string;
  party:        string;
  partySymbol:  string;
  constituency: string;
};

export type BallotItem = {
  candidate: Candidate;
  position:  number;
};

export type VoteReceipt = {
  vid:            string;
  votedAt:        string;
  constituencyId: string;
  receiptHash:    string;
};

export type VotingStatus =
  | "idle"
  | "loading_ballot"
  | "ballot_ready"
  | "submitting"
  | "submitted"
  | "error";

/* ══════════════════════════════════════
   API payloads
══════════════════════════════════════ */
export type RegisterPayload = {
  aadhaar_id: string;
  voter_id:   string;
};

export type LivenessPayload = {
  voter_id:     string;
  image_base64: string;
};

export type VotePayload = {
  voter_id:      string;
  candidate_id:  string;
  session_token: string;
};

/* ══════════════════════════════════════
   API responses
══════════════════════════════════════ */
export type RegisterResponse = {
  session_token: string;
  voter_id:      string;
  message:       string;
};

export type LivenessResponse = {
  passed:        boolean;
  session_token: string;
  message:       string;
};

export type BallotResponse = {
  constituency_id: string;
  candidates: Array<{
    id:           string;
    name:         string;
    party:        string;
    party_symbol: string;
    constituency: string;
    position:     number;
  }>;
};

export type VoteResponse = {
  vid:             string;
  voted_at:        string;
  constituency_id: string;
  receipt_hash:    string;
  message:         string;
};

export type VerifyResponse = {
  vid:             string;
  voted_at:        string;
  constituency_id: string;
  candidate_name:  string;
  party:           string;
  receipt_hash:    string;
};

/* ══════════════════════════════════════
   UI helpers
══════════════════════════════════════ */
export type LoadingState = "idle" | "loading" | "success" | "error";

export type ToastType = "success" | "error" | "info" | "warning";

export type Toast = {
  id:      string;
  type:    ToastType;
  message: string;
};