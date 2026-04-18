import axios, {
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from "axios";
import { useAuthStore } from "../store/authStore";

/* ══════════════════════════════════════
   Config
══════════════════════════════════════ */
const BASE_URL     = "http://10.252.102.243:8000";
const TIMEOUT_MS   = 10_000;
const API_VERSION  = "api/v1";

/* ══════════════════════════════════════
   Axios instance
══════════════════════════════════════ */
export const apiClient: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}${API_VERSION}`,
  timeout: TIMEOUT_MS,
  headers: {
    "Content-Type": "application/json",
    Accept:         "application/json",
  },
});

/* ══════════════════════════════════════
   Request interceptor
   — attaches session token if present
══════════════════════════════════════ */
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = useAuthStore.getState().voter?.sessionToken;

    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    if (__DEV__) {
      console.log(
        `[API →] ${config.method?.toUpperCase()} ${config.baseURL}${config.url}`,
        config.data ?? ""
      );
    }

    return config;
  },
  (error) => {
    console.error("[API request error]", error);
    return Promise.reject(error);
  }
);

/* ══════════════════════════════════════
   Response interceptor
   — normalizes errors
══════════════════════════════════════ */
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    if (__DEV__) {
      console.log(
        `[API ←] ${response.status} ${response.config.url}`,
        response.data
      );
    }
    return response;
  },
  (error) => {
    const status  = error.response?.status;
    const detail  = error.response?.data?.detail;
    const message = error.response?.data?.message;

    if (__DEV__) {
      console.error(`[API error] ${status}`, error.response?.data ?? error.message);
    }

    /* ── Map status codes to readable messages ── */
    const readable = resolveErrorMessage(status, detail ?? message ?? error.message);

    return Promise.reject(new ApiError(readable, status, error.response?.data));
  }
);

/* ══════════════════════════════════════
   ApiError — typed error class
══════════════════════════════════════ */
export class ApiError extends Error {
  status:   number | undefined;
  payload:  unknown;

  constructor(message: string, status?: number, payload?: unknown) {
    super(message);
    this.name    = "ApiError";
    this.status  = status;
    this.payload = payload;
  }
}

/* ══════════════════════════════════════
   Error message resolver
══════════════════════════════════════ */
function resolveErrorMessage(
  status: number | undefined,
  fallback: string
): string {
  switch (status) {
    case 400: return "Invalid request. Please check your details.";
    case 401: return "Session expired. Please re-authenticate.";
    case 403: return "Access denied. You are not authorized.";
    case 404: return "Resource not found.";
    case 409: return "Conflict — you may have already voted.";
    case 422: return "Validation failed. Please check your inputs.";
    case 429: return "Too many requests. Please wait and try again.";
    case 500: return "Server error. Please try again shortly.";
    case 503: return "Service unavailable. Please try again later.";
    default:  return fallback ?? "An unexpected error occurred.";
  }
}

/* ══════════════════════════════════════
   API endpoint functions
══════════════════════════════════════ */

/* ── Health check ── */
export async function checkHealth(): Promise<{ status: string }> {
  const res = await apiClient.get("/health");
  return res.data;
}

/* ── Register voter ── */
export type RegisterPayload = {
  aadhaar_id: string;
  voter_id:   string;
};

export type RegisterResponse = {
  session_token: string;
  voter_id:      string;
  message:       string;
};

export async function registerVoter(
  payload: RegisterPayload
): Promise<RegisterResponse> {
  const res = await apiClient.post<RegisterResponse>("/auth/register", payload);
  return res.data;
}

/* ── Liveness verification ── */
export type LivenessPayload = {
  voter_id:    string;
  image_base64: string;
};

export type LivenessResponse = {
  passed:        boolean;
  session_token: string;
  message:       string;
};

export async function verifyLiveness(
  payload: LivenessPayload
): Promise<LivenessResponse> {
  const res = await apiClient.post<LivenessResponse>("/auth/liveness", payload);
  return res.data;
}

/* ── Fetch ballot ── */
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

export async function fetchBallot(
  constituencyId: string
): Promise<BallotResponse> {
  const res = await apiClient.get<BallotResponse>(`/ballot/${constituencyId}`);
  return res.data;
}

/* ── Submit vote ── */
export type VotePayload = {
  voter_id:     string;
  candidate_id: string;
  session_token: string;
};

export type VoteResponse = {
  vid:             string;
  voted_at:        string;
  constituency_id: string;
  receipt_hash:    string;
  message:         string;
};

export async function submitVote(
  payload: VotePayload
): Promise<VoteResponse> {
  const res = await apiClient.post<VoteResponse>("/vote/submit", payload);
  return res.data;
}

/* ── Verify vote by VID ── */
export type VerifyResponse = {
  vid:             string;
  voted_at:        string;
  constituency_id: string;
  candidate_name:  string;
  party:           string;
  receipt_hash:    string;
};

export async function verifyVote(vid: string): Promise<VerifyResponse> {
  const res = await apiClient.get<VerifyResponse>(`/vote/verify/${vid}`);
  return res.data;
}