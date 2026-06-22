// Core domain types for the Checkpoint review system.
// The primary object is a Session, not a commit.

export type SessionStatus =
  | "active"
  | "accepted"
  | "rejected"
  | "rolled_back"
  | "merged"

export type ActorType = "human" | "agent" | "ci" | "machine" | "service"

export interface Session {
  session_id: string
  instruction: string
  status: SessionStatus
  actor_identity: string
  actor_type: ActorType
  agent_name?: string
  model_name?: string
  tool_name?: string
  started_at: string
  branch: string
  base_snapshot: string
  accepted_snapshot?: string
  risk_tags: string[]
  // derived/review badges
  verification_status: VerificationStatus
  policy_effect: PolicyEffect
  signature_status: SignatureStatus
  fsck_status: FsckStatus
  summary?: string
}

export type TimelineEventType =
  | "session_started"
  | "autosave_created"
  | "snapshot_created"
  | "verification_run"
  | "policy_check"
  | "signature_created"
  | "accepted"
  | "rejected"
  | "rolled_back"
  | "merged"
  | "pushed"
  | "fetched"

export interface TimelineEvent {
  id: string
  type: TimelineEventType
  at: string
  title: string
  detail?: string
  actor?: string
  // autosaves are recovery-only, not accepted history
  recovery_only?: boolean
  object_id?: string
}

export type ChangeType =
  | "added"
  | "deleted"
  | "modified"
  | "renamed"
  | "binary"
  | "conflict"

export interface DiffHunk {
  header: string
  lines: DiffLine[]
}

export interface DiffLine {
  kind: "context" | "add" | "del" | "conflict-ours" | "conflict-theirs" | "conflict-marker"
  text: string
}

export interface DiffFile {
  old_path: string
  new_path: string
  change_type: ChangeType
  similarity?: number
  additions: number
  deletions: number
  hunks: DiffHunk[]
}

export type VerificationStatus = "passed" | "failed" | "skipped"

export interface VerificationResult {
  command: string
  status: VerificationStatus
  duration_ms: number
  summary: string
  stdout_excerpt?: string
  stderr_excerpt?: string
}

export type PolicyEffect = "allow" | "deny" | "warn"

export interface PolicyDecision {
  effect: PolicyEffect
  matched_rules: string[]
  reasons: string[]
  required_actions: string[]
  override_available: boolean
  override_used: boolean
}

export type TrustStatus = "trusted" | "untrusted" | "unknown" | "revoked"
export type SignatureValidity = "valid" | "invalid" | "unsigned"
export type SignatureStatus = SignatureValidity

export interface Signature {
  signer_name: string
  signer_type: ActorType
  trust_status: TrustStatus
  status: SignatureValidity
  signed_at?: string
  fingerprint?: string
}

export type FsckStatus = "healthy" | "warnings" | "corrupt"

export interface Integrity {
  fsck_status: FsckStatus
  seal_status: "sealed" | "unsealed"
  object_count: number
  dangling_count: number
  corrupt_count: number
  missing_count: number
  last_gc_result: string
}

export interface Identity {
  name: string
  type: ActorType
  fingerprint: string
  trust_status: TrustStatus
  created_at: string
  capabilities: string[]
}

export interface AuditEvent {
  id: string
  timestamp: string
  actor: string
  operation: string
  result: "success" | "denied" | "error"
  policy_decision?: PolicyEffect
  ref_update?: string
  server_receipt?: string
}

export interface PolicyConfig {
  protected_branches: string[]
  path_rules: { pattern: string; rule: string }[]
  actor_rules: { actor: string; rule: string }[]
  remote_rules: string[]
  override_rules: string[]
}

export interface Branch {
  name: string
  accepted_snapshot: string
  last_session?: string
  ahead: number
  behind: number
}

export interface Repo {
  owner: string
  name: string
  branch_count: number
  recent_sessions: number
  latest_accepted_snapshot: string
  policy_status: PolicyEffect
  signature_status: SignatureValidity
  trust_status: TrustStatus
  fsck_status: FsckStatus
  alerts: RepoAlert[]
}

export interface RepoAlert {
  kind: "unsigned_accepted" | "policy_violation" | "corrupt_store" | "untrusted_signer"
  message: string
}

export interface HealthStatus {
  ok: boolean
  version: string
  uptime_s: number
}

export interface SessionPacket {
  instruction: string
  summary: string
  risk_tags: string[]
  changed_paths: string[]
  recommended_action: string
  accepted_snapshot?: string
}
