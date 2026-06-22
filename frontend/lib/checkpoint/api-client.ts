import {
  mockAudit,
  mockBranches,
  mockDiffsBySession,
  mockHealth,
  mockIdentities,
  mockIntegrity,
  mockPacketBySession,
  mockPolicyBySession,
  mockPolicyConfig,
  mockRepos,
  mockSessions,
  mockSignaturesBySession,
  mockTimelineBySession,
  mockVerificationBySession,
} from "./mock-data"
import type {
  AuditEvent,
  Branch,
  DiffFile,
  HealthStatus,
  Identity,
  Integrity,
  PolicyConfig,
  PolicyDecision,
  Repo,
  Session,
  SessionPacket,
  Signature,
  TimelineEvent,
  VerificationResult,
  MergeRequest,
  MergeRequestDetail,
  MRComment,
} from "./types"

export const STORAGE_KEYS = {
  token: "checkpoint_token",
  baseUrl: "checkpoint_base_url",
} as const

// The Checkpoint hosted server (`checkpoint-server start`) defaults to :8800 and serves a
// frontend-shaped adapter under /ui/* (see UI_PREFIX). Override on the login screen.
export const DEFAULT_BASE_URL = "http://localhost:8800"

// All UI data flows through the server's backend-for-frontend adapter at /ui/*.
// (The protocol-shaped API lives at the un-prefixed paths and is used by the CLI.)
export const UI_PREFIX = "/ui"

export interface ApiResult<T> {
  data: T
  isMock: boolean
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

function getConfig() {
  if (typeof window === "undefined") {
    return { token: "", baseUrl: DEFAULT_BASE_URL }
  }
  return {
    token: localStorage.getItem(STORAGE_KEYS.token) ?? "",
    baseUrl: localStorage.getItem(STORAGE_KEYS.baseUrl) ?? DEFAULT_BASE_URL,
  }
}

export function setSession(token: string, baseUrl: string) {
  localStorage.setItem(STORAGE_KEYS.token, token)
  localStorage.setItem(STORAGE_KEYS.baseUrl, baseUrl || DEFAULT_BASE_URL)
}

export function clearSession() {
  localStorage.removeItem(STORAGE_KEYS.token)
  localStorage.removeItem(STORAGE_KEYS.baseUrl)
}

export function isAuthenticated() {
  if (typeof window === "undefined") return false
  return Boolean(localStorage.getItem(STORAGE_KEYS.token))
}

/**
 * Attempts a real API call. If the backend is unavailable (network error),
 * resolves with the provided mock fallback and isMock = true.
 * Real HTTP error statuses are thrown so callers can route 401 -> login, etc.
 */
async function request<T>(path: string, fallback: T, init?: RequestInit): Promise<ApiResult<T>> {
  const { token, baseUrl } = getConfig()

  try {
    const res = await fetch(`${baseUrl}${UI_PREFIX}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
      signal: AbortSignal.timeout(12000),
    })

    if (res.status === 401) {
      if (typeof window !== "undefined") {
        clearSession()
        window.location.href = "/login"
      }
      throw new ApiError(401, "Unauthorized")
    }
    if (res.status === 403) throw new ApiError(403, "You do not have permission to view this resource.")
    if (res.status === 404) throw new ApiError(404, "Not found.")
    if (res.status >= 500) throw new ApiError(res.status, "The Checkpoint server encountered an error.")
    if (!res.ok) throw new ApiError(res.status, `Request failed (${res.status}).`)

    const data = (await res.json()) as T
    return { data, isMock: false }
  } catch (err) {
    if (err instanceof ApiError) throw err
    // Network / timeout / CORS -> fall back to mock data.
    return { data: fallback, isMock: true }
  }
}

export const api = {
  getHealth: () => request<HealthStatus>("/health", mockHealth),

  listRepos: () => request<Repo[]>("/repos", mockRepos),

  getRepo: (owner: string, repo: string) =>
    request<Repo>(
      `/repos/${owner}/${repo}`,
      mockRepos.find((r) => r.owner === owner && r.name === repo) ?? mockRepos[0],
    ),

  listSessions: (owner: string, repo: string) =>
    request<Session[]>(`/repos/${owner}/${repo}/sessions`, mockSessions),

  getSession: (owner: string, repo: string, sessionId: string) =>
    request<Session>(
      `/repos/${owner}/${repo}/sessions/${sessionId}`,
      mockSessions.find((s) => s.session_id === sessionId) ?? mockSessions[0],
    ),

  getTimeline: (owner: string, repo: string, sessionId: string) =>
    request<TimelineEvent[]>(
      `/repos/${owner}/${repo}/sessions/${sessionId}/timeline`,
      mockTimelineBySession[sessionId] ?? [],
    ),

  getDiff: (owner: string, repo: string, sessionId: string) =>
    request<DiffFile[]>(
      `/repos/${owner}/${repo}/sessions/${sessionId}/diff`,
      mockDiffsBySession[sessionId] ?? [],
    ),

  getPacket: (owner: string, repo: string, sessionId: string) =>
    request<SessionPacket | null>(
      `/repos/${owner}/${repo}/sessions/${sessionId}/packet`,
      mockPacketBySession[sessionId] ?? null,
    ),

  getVerification: (owner: string, repo: string, sessionId: string) =>
    request<VerificationResult[]>(
      `/repos/${owner}/${repo}/sessions/${sessionId}/verification`,
      mockVerificationBySession[sessionId] ?? [],
    ),

  getPolicyDecision: (owner: string, repo: string, sessionId: string) =>
    request<PolicyDecision | null>(
      `/repos/${owner}/${repo}/sessions/${sessionId}/policy`,
      mockPolicyBySession[sessionId] ?? null,
    ),

  getSignatures: (owner: string, repo: string, sessionId: string) =>
    request<Signature[]>(
      `/repos/${owner}/${repo}/sessions/${sessionId}/signatures`,
      mockSignaturesBySession[sessionId] ?? [],
    ),

  getSessionIntegrity: (owner: string, repo: string, _sessionId: string) =>
    request<Integrity>(`/repos/${owner}/${repo}/integrity`, mockIntegrity),

  getPolicy: (owner: string, repo: string) =>
    request<PolicyConfig>(`/repos/${owner}/${repo}/policy`, mockPolicyConfig),

  checkPolicy: (owner: string, repo: string, input: unknown) =>
    request<PolicyDecision>(`/repos/${owner}/${repo}/policy/check`, mockPolicyBySession.sess_c3d75e2a8b16, {
      method: "POST",
      body: JSON.stringify(input),
    }),

  listBranches: (owner: string, repo: string) =>
    request<Branch[]>(`/repos/${owner}/${repo}/branches`, mockBranches),

  listIdentities: (owner: string, repo: string) =>
    request<Identity[]>(`/repos/${owner}/${repo}/identities`, mockIdentities),

  setIdentityTrust: (owner: string, repo: string, id: string, op: "trust" | "untrust" | "revoke") =>
    request<{ id: string; op: string; trust_status?: string }>(
      `/repos/${owner}/${repo}/identities/${id}/${op}`,
      { id, op },
      { method: "POST" },
    ),

  runFsck: (owner: string, repo: string) =>
    request<Integrity>(`/repos/${owner}/${repo}/fsck`, mockIntegrity, { method: "POST" }),

  verifySignatures: (owner: string, repo: string) =>
    request<Signature[]>(`/repos/${owner}/${repo}/signatures/verify`, mockSignaturesBySession.sess_a1f93c2e7b04, {
      method: "POST",
    }),

  getAudit: (owner: string, repo: string) =>
    request<AuditEvent[]>(`/repos/${owner}/${repo}/audit`, mockAudit),

  // --- merge requests ---
  listReviews: (owner: string, repo: string) =>
    request<MergeRequest[]>(`/repos/${owner}/${repo}/reviews`, []),

  createReview: (owner: string, repo: string, input: unknown) =>
    request<MergeRequest>(`/repos/${owner}/${repo}/reviews`, {} as MergeRequest, {
      method: "POST",
      body: JSON.stringify(input),
    }),

  getReview: (owner: string, repo: string, id: string) =>
    request<MergeRequestDetail>(`/repos/${owner}/${repo}/reviews/${id}`, {} as MergeRequestDetail),

  addReviewComment: (owner: string, repo: string, id: string, input: unknown) =>
    request<MRComment>(`/repos/${owner}/${repo}/reviews/${id}/comments`, {} as MRComment, {
      method: "POST",
      body: JSON.stringify(input),
    }),

  resolveReviewComment: (owner: string, repo: string, id: string, cid: string, resolved: boolean) =>
    request<MRComment>(`/repos/${owner}/${repo}/reviews/${id}/comments/${cid}/resolve`, {} as MRComment, {
      method: "POST",
      body: JSON.stringify({ resolved }),
    }),

  mergeReview: (owner: string, repo: string, id: string) =>
    request<{ status: string; reasons?: string[]; conflicts?: string[]; snapshot?: string }>(
      `/repos/${owner}/${repo}/reviews/${id}/merge`,
      { status: "merged" },
      { method: "POST" },
    ),

  closeReview: (owner: string, repo: string, id: string) =>
    request<MergeRequest>(`/repos/${owner}/${repo}/reviews/${id}/close`, {} as MergeRequest, {
      method: "POST",
    }),

  approveReview: (owner: string, repo: string, id: string, approve: boolean) =>
    request<MergeRequest>(`/repos/${owner}/${repo}/reviews/${id}/approve`, {} as MergeRequest, {
      method: "POST",
      body: JSON.stringify({ approve }),
    }),

  getIntegrity: (owner: string, repo: string) =>
    request<Integrity>(`/repos/${owner}/${repo}/integrity`, mockIntegrity),
}
