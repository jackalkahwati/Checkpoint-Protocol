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
} from "./types"

export const mockHealth: HealthStatus = {
  ok: true,
  version: "0.4.2",
  uptime_s: 184213,
}

export const mockRepos: Repo[] = [
  {
    owner: "jack",
    name: "checkpoint-protocol",
    branch_count: 4,
    recent_sessions: 12,
    latest_accepted_snapshot: "snap_9f2c41ab7d3e",
    policy_status: "warn",
    signature_status: "valid",
    trust_status: "trusted",
    fsck_status: "healthy",
    alerts: [
      {
        kind: "policy_violation",
        message: "1 active session denied on safety-critical path",
      },
      {
        kind: "untrusted_signer",
        message: "Session 'Refactor merge engine' is unsigned",
      },
    ],
  },
  {
    owner: "jack",
    name: "checkpoint-core",
    branch_count: 7,
    recent_sessions: 31,
    latest_accepted_snapshot: "snap_3a81be90c2f4",
    policy_status: "allow",
    signature_status: "valid",
    trust_status: "trusted",
    fsck_status: "healthy",
    alerts: [],
  },
  {
    owner: "labs",
    name: "verification-runner",
    branch_count: 2,
    recent_sessions: 5,
    latest_accepted_snapshot: "snap_7c40fa1182bd",
    policy_status: "allow",
    signature_status: "unsigned",
    trust_status: "untrusted",
    fsck_status: "warnings",
    alerts: [
      {
        kind: "unsigned_accepted",
        message: "2 accepted snapshots have no signature",
      },
    ],
  },
]

export const mockSessions: Session[] = [
  {
    session_id: "sess_a1f93c2e7b04",
    instruction: "Implement remote sync without trusting the remote",
    status: "accepted",
    actor_identity: "Jack Al-Kahwati",
    actor_type: "agent",
    agent_name: "claude-code",
    model_name: "claude-opus-4.6",
    tool_name: "checkpoint-agent",
    started_at: "2026-06-21T14:02:11Z",
    branch: "feature/remote-sync",
    base_snapshot: "snap_1b77ce0a93fd",
    accepted_snapshot: "snap_9f2c41ab7d3e",
    risk_tags: ["network", "trust-boundary"],
    verification_status: "passed",
    policy_effect: "allow",
    signature_status: "valid",
    fsck_status: "healthy",
    summary:
      "Adds pull/fetch that treats the remote as untrusted: all incoming objects are re-verified locally before they can enter accepted history.",
  },
  {
    session_id: "sess_b2e84d1f6a55",
    instruction: "Add policy engine for safety-critical paths",
    status: "accepted",
    actor_identity: "claude-code",
    actor_type: "agent",
    agent_name: "claude-code",
    model_name: "claude-opus-4.6",
    tool_name: "checkpoint-agent",
    started_at: "2026-06-20T09:41:55Z",
    branch: "feature/policy-engine",
    base_snapshot: "snap_55aa20fe11cc",
    accepted_snapshot: "snap_c0ffee123456",
    risk_tags: ["safety-critical"],
    verification_status: "passed",
    policy_effect: "allow",
    signature_status: "valid",
    fsck_status: "healthy",
    summary:
      "Introduces a path-scoped policy engine that requires trusted human acceptance for safety-critical files.",
  },
  {
    session_id: "sess_c3d75e2a8b16",
    instruction: "Refactor merge engine with rename detection",
    status: "active",
    actor_identity: "claude-code",
    actor_type: "agent",
    agent_name: "claude-code",
    model_name: "claude-sonnet-4.6",
    tool_name: "checkpoint-agent",
    started_at: "2026-06-22T08:15:30Z",
    branch: "feature/merge-rename",
    base_snapshot: "snap_9f2c41ab7d3e",
    risk_tags: ["safety-critical", "merge"],
    verification_status: "failed",
    policy_effect: "warn",
    signature_status: "unsigned",
    fsck_status: "healthy",
    summary:
      "Rewrites the merge engine to detect renames via similarity scoring. Verification currently failing on conflict edge cases.",
  },
]

const renameDiff: DiffFile = {
  old_path: "checkpoint_core/merge.py",
  new_path: "checkpoint_core/merge_engine.py",
  change_type: "renamed",
  similarity: 84,
  additions: 42,
  deletions: 18,
  hunks: [
    {
      header: "@@ -1,12 +1,18 @@ class MergeEngine",
      lines: [
        { kind: "context", text: "class MergeEngine:" },
        { kind: "context", text: "    def __init__(self, store):" },
        { kind: "del", text: "        self.store = store" },
        { kind: "add", text: "        self.store = store" },
        { kind: "add", text: "        self.rename_threshold = 0.5" },
        { kind: "context", text: "" },
        { kind: "del", text: "    def merge(self, base, ours, theirs):" },
        { kind: "add", text: "    def merge(self, base, ours, theirs, detect_renames=True):" },
        { kind: "add", text: "        if detect_renames:" },
        { kind: "add", text: "            renames = self._detect_renames(base, ours, theirs)" },
        { kind: "context", text: "        result = self._three_way(base, ours, theirs)" },
        { kind: "context", text: "        return result" },
      ],
    },
  ],
}

const modifiedDiff: DiffFile = {
  old_path: "docs/checkpoint-core-protocol.md",
  new_path: "docs/checkpoint-core-protocol.md",
  change_type: "modified",
  additions: 9,
  deletions: 2,
  hunks: [
    {
      header: "@@ -44,7 +44,14 @@ ## Merge semantics",
      lines: [
        { kind: "context", text: "## Merge semantics" },
        { kind: "context", text: "" },
        { kind: "del", text: "Merges are three-way and content addressed." },
        { kind: "add", text: "Merges are three-way and content addressed." },
        { kind: "add", text: "" },
        { kind: "add", text: "### Rename detection" },
        { kind: "add", text: "" },
        { kind: "add", text: "When a file is deleted on one side and added on the" },
        { kind: "add", text: "other, the merge engine computes a similarity score." },
        { kind: "add", text: "If similarity >= 50%, the change is treated as a rename" },
        { kind: "add", text: "plus edit rather than a delete/add pair." },
        { kind: "context", text: "" },
      ],
    },
  ],
}

const addedDiff: DiffFile = {
  old_path: "/dev/null",
  new_path: "checkpoint_core/rename_detect.py",
  change_type: "added",
  additions: 28,
  deletions: 0,
  hunks: [
    {
      header: "@@ -0,0 +1,28 @@",
      lines: [
        { kind: "add", text: "from difflib import SequenceMatcher" },
        { kind: "add", text: "" },
        { kind: "add", text: "def similarity(a: bytes, b: bytes) -> float:" },
        { kind: "add", text: '    """Return a 0..1 similarity ratio between two blobs."""' },
        { kind: "add", text: "    return SequenceMatcher(None, a, b).ratio()" },
        { kind: "add", text: "" },
        { kind: "add", text: "def detect_renames(deleted, added, threshold=0.5):" },
        { kind: "add", text: "    pairs = []" },
        { kind: "add", text: "    for d in deleted:" },
        { kind: "add", text: "        best = max(added, key=lambda a: similarity(d.data, a.data))" },
        { kind: "add", text: "        if similarity(d.data, best.data) >= threshold:" },
        { kind: "add", text: "            pairs.append((d.path, best.path))" },
        { kind: "add", text: "    return pairs" },
      ],
    },
  ],
}

const conflictDiff: DiffFile = {
  old_path: "checkpoint_core/safety/controller.rs",
  new_path: "checkpoint_core/safety/controller.rs",
  change_type: "conflict",
  additions: 6,
  deletions: 4,
  hunks: [
    {
      header: "@@ -88,10 +88,16 @@ impl SafetyController",
      lines: [
        { kind: "context", text: "    pub fn evaluate(&self, op: &Operation) -> Decision {" },
        { kind: "context", text: "        let path = op.target_path();" },
        { kind: "conflict-marker", text: "<<<<<<< ours" },
        { kind: "conflict-ours", text: "        if self.is_safety_critical(path) {" },
        { kind: "conflict-ours", text: "            return Decision::RequireTrustedHuman;" },
        { kind: "conflict-marker", text: "=======" },
        { kind: "conflict-theirs", text: "        if self.is_protected(path) {" },
        { kind: "conflict-theirs", text: "            return Decision::Deny(\"protected path\");" },
        { kind: "conflict-marker", text: ">>>>>>> theirs" },
        { kind: "context", text: "        }" },
        { kind: "context", text: "        Decision::Allow" },
        { kind: "context", text: "    }" },
      ],
    },
  ],
}

const deletedDiff: DiffFile = {
  old_path: "checkpoint_core/legacy_merge.py",
  new_path: "/dev/null",
  change_type: "deleted",
  additions: 0,
  deletions: 14,
  hunks: [
    {
      header: "@@ -1,14 +0,0 @@",
      lines: [
        { kind: "del", text: "# Deprecated in favour of merge_engine.py" },
        { kind: "del", text: "def naive_merge(ours, theirs):" },
        { kind: "del", text: "    return ours + theirs" },
      ],
    },
  ],
}

const binaryDiff: DiffFile = {
  old_path: "docs/assets/merge-diagram.png",
  new_path: "docs/assets/merge-diagram.png",
  change_type: "binary",
  additions: 0,
  deletions: 0,
  hunks: [],
}

export const mockDiffsBySession: Record<string, DiffFile[]> = {
  sess_c3d75e2a8b16: [
    renameDiff,
    modifiedDiff,
    addedDiff,
    conflictDiff,
    deletedDiff,
    binaryDiff,
  ],
  sess_a1f93c2e7b04: [modifiedDiff, addedDiff],
  sess_b2e84d1f6a55: [addedDiff, modifiedDiff],
}

export const mockTimelineBySession: Record<string, TimelineEvent[]> = {
  sess_c3d75e2a8b16: [
    {
      id: "ev1",
      type: "session_started",
      at: "2026-06-22T08:15:30Z",
      title: "Session started",
      detail: "claude-code (claude-sonnet-4.6) opened a session",
      actor: "claude-code",
      object_id: "snap_9f2c41ab7d3e",
    },
    {
      id: "ev2",
      type: "autosave_created",
      at: "2026-06-22T08:18:02Z",
      title: "Autosave created",
      detail: "Recovery-only state, not accepted history",
      recovery_only: true,
      object_id: "auto_4412de",
    },
    {
      id: "ev3",
      type: "snapshot_created",
      at: "2026-06-22T08:24:47Z",
      title: "Snapshot created",
      detail: "Meaningful intermediate state: rename detection scaffolding",
      object_id: "snap_aa19f0",
    },
    {
      id: "ev4",
      type: "autosave_created",
      at: "2026-06-22T08:31:15Z",
      title: "Autosave created",
      detail: "Recovery-only state, not accepted history",
      recovery_only: true,
      object_id: "auto_5519ef",
    },
    {
      id: "ev5",
      type: "verification_run",
      at: "2026-06-22T08:40:09Z",
      title: "Verification run",
      detail: "pytest -q tests/merge — 2 failed, 41 passed",
      object_id: "ver_77a1",
    },
    {
      id: "ev6",
      type: "policy_check",
      at: "2026-06-22T08:40:30Z",
      title: "Policy check",
      detail: "warn: safety-critical path touched without trusted human acceptor",
      object_id: "pol_22b9",
    },
  ],
  sess_a1f93c2e7b04: [
    {
      id: "e1",
      type: "session_started",
      at: "2026-06-21T14:02:11Z",
      title: "Session started",
      actor: "claude-code",
      object_id: "snap_1b77ce0a93fd",
    },
    {
      id: "e2",
      type: "snapshot_created",
      at: "2026-06-21T14:30:00Z",
      title: "Snapshot created",
      detail: "Untrusted remote verification layer",
      object_id: "snap_33ad",
    },
    {
      id: "e3",
      type: "verification_run",
      at: "2026-06-21T14:52:40Z",
      title: "Verification run",
      detail: "cargo test — all passed",
      object_id: "ver_11",
    },
    {
      id: "e4",
      type: "policy_check",
      at: "2026-06-21T14:53:01Z",
      title: "Policy check",
      detail: "allow",
      object_id: "pol_12",
    },
    {
      id: "e5",
      type: "signature_created",
      at: "2026-06-21T15:01:22Z",
      title: "Signature created",
      detail: "Signed by Jack Al-Kahwati (trusted human)",
      object_id: "sig_98",
    },
    {
      id: "e6",
      type: "accepted",
      at: "2026-06-21T15:02:00Z",
      title: "Accepted",
      detail: "Accepted snapshot snap_9f2c41ab7d3e",
      actor: "Jack Al-Kahwati",
      object_id: "snap_9f2c41ab7d3e",
    },
    {
      id: "e7",
      type: "pushed",
      at: "2026-06-21T15:05:11Z",
      title: "Pushed",
      detail: "Pushed to origin with server receipt",
      object_id: "rcpt_4a",
    },
  ],
  sess_b2e84d1f6a55: [
    {
      id: "p1",
      type: "session_started",
      at: "2026-06-20T09:41:55Z",
      title: "Session started",
      actor: "claude-code",
    },
    {
      id: "p2",
      type: "snapshot_created",
      at: "2026-06-20T10:10:00Z",
      title: "Snapshot created",
      detail: "Path-scoped policy engine",
    },
    {
      id: "p3",
      type: "verification_run",
      at: "2026-06-20T10:30:00Z",
      title: "Verification run",
      detail: "pytest — all passed",
    },
    {
      id: "p4",
      type: "signature_created",
      at: "2026-06-20T10:45:00Z",
      title: "Signature created",
      detail: "Signed by Jack Al-Kahwati (trusted human)",
    },
    {
      id: "p5",
      type: "accepted",
      at: "2026-06-20T10:46:00Z",
      title: "Accepted",
      detail: "Accepted snapshot snap_c0ffee123456",
      actor: "Jack Al-Kahwati",
    },
  ],
}

export const mockPacketBySession: Record<string, SessionPacket> = {
  sess_c3d75e2a8b16: {
    instruction: "Refactor merge engine with rename detection",
    summary:
      "Rewrites checkpoint_core/merge.py into merge_engine.py and adds similarity-based rename detection. Adds a new rename_detect module and updates protocol docs. Touches a safety-critical controller file with an unresolved conflict.",
    risk_tags: ["safety-critical", "merge"],
    changed_paths: [
      "checkpoint_core/merge_engine.py",
      "checkpoint_core/rename_detect.py",
      "checkpoint_core/safety/controller.rs",
      "docs/checkpoint-core-protocol.md",
    ],
    recommended_action: "Resolve conflict and rerun safety_tests before acceptance.",
  },
  sess_a1f93c2e7b04: {
    instruction: "Implement remote sync without trusting the remote",
    summary:
      "Incoming objects from a remote are re-verified locally before entering accepted history. No remote signature is trusted by default.",
    risk_tags: ["network", "trust-boundary"],
    changed_paths: ["checkpoint_core/remote.py", "docs/checkpoint-core-protocol.md"],
    recommended_action: "Accept — verification passed and signed by trusted human.",
    accepted_snapshot: "snap_9f2c41ab7d3e",
  },
}

export const mockVerificationBySession: Record<string, VerificationResult[]> = {
  sess_c3d75e2a8b16: [
    {
      command: "pytest -q tests/merge",
      status: "failed",
      duration_ms: 8412,
      summary: "2 failed, 41 passed",
      stdout_excerpt: "41 passed",
      stderr_excerpt:
        "FAILED tests/merge/test_conflict.py::test_rename_with_conflict\nFAILED tests/merge/test_conflict.py::test_three_way_safety",
    },
    {
      command: "cargo test -p safety",
      status: "skipped",
      duration_ms: 0,
      summary: "Skipped: blocked on unresolved conflict in controller.rs",
    },
  ],
  sess_a1f93c2e7b04: [
    {
      command: "cargo test --workspace",
      status: "passed",
      duration_ms: 19342,
      summary: "212 passed",
      stdout_excerpt: "test result: ok. 212 passed; 0 failed",
    },
  ],
  sess_b2e84d1f6a55: [
    {
      command: "pytest -q",
      status: "passed",
      duration_ms: 6120,
      summary: "88 passed",
      stdout_excerpt: "88 passed",
    },
  ],
}

export const mockPolicyBySession: Record<string, PolicyDecision> = {
  sess_c3d75e2a8b16: {
    effect: "deny",
    matched_rules: ["path:safety-critical", "actor:agent-no-trusted-human"],
    reasons: [
      "Denied because checkpoint_core/safety/controller.rs requires a trusted human acceptor.",
      "The current session has no trusted human signature.",
    ],
    required_actions: [
      "Switch to a trusted human identity and re-accept.",
      "Resolve the conflict in controller.rs.",
      "Rerun safety_tests and ensure they pass.",
    ],
    override_available: false,
    override_used: false,
  },
  sess_a1f93c2e7b04: {
    effect: "allow",
    matched_rules: ["path:default", "actor:trusted-human"],
    reasons: ["Operation allowed: verification passed and signed by a trusted human."],
    required_actions: [],
    override_available: true,
    override_used: false,
  },
  sess_b2e84d1f6a55: {
    effect: "allow",
    matched_rules: ["path:safety-critical", "actor:trusted-human"],
    reasons: ["Safety-critical path accepted by a trusted human identity."],
    required_actions: [],
    override_available: true,
    override_used: false,
  },
}

export const mockSignaturesBySession: Record<string, Signature[]> = {
  sess_c3d75e2a8b16: [
    {
      signer_name: "—",
      signer_type: "agent",
      trust_status: "untrusted",
      status: "unsigned",
    },
  ],
  sess_a1f93c2e7b04: [
    {
      signer_name: "Jack Al-Kahwati",
      signer_type: "human",
      trust_status: "trusted",
      status: "valid",
      signed_at: "2026-06-21T15:01:22Z",
      fingerprint: "SHA256:9a4f2c1e8b7d3a05f6c9e2b1a8d7f4c30e1b2a9d",
    },
  ],
  sess_b2e84d1f6a55: [
    {
      signer_name: "Jack Al-Kahwati",
      signer_type: "human",
      trust_status: "trusted",
      status: "valid",
      signed_at: "2026-06-20T10:45:00Z",
      fingerprint: "SHA256:9a4f2c1e8b7d3a05f6c9e2b1a8d7f4c30e1b2a9d",
    },
  ],
}

export const mockIntegrity: Integrity = {
  fsck_status: "healthy",
  seal_status: "sealed",
  object_count: 48213,
  dangling_count: 3,
  corrupt_count: 0,
  missing_count: 0,
  last_gc_result: "Reclaimed 1,204 objects (38.2 MB) on 2026-06-21",
}

export const mockBranches: Branch[] = [
  { name: "main", accepted_snapshot: "snap_9f2c41ab7d3e", last_session: "Implement remote sync", ahead: 0, behind: 0 },
  { name: "feature/remote-sync", accepted_snapshot: "snap_9f2c41ab7d3e", last_session: "Implement remote sync", ahead: 0, behind: 0 },
  { name: "feature/policy-engine", accepted_snapshot: "snap_c0ffee123456", last_session: "Add policy engine", ahead: 2, behind: 1 },
  { name: "feature/merge-rename", accepted_snapshot: "snap_aa19f0", last_session: "Refactor merge engine", ahead: 5, behind: 3 },
]

export const mockPolicyConfig: PolicyConfig = {
  protected_branches: ["main", "release/*"],
  path_rules: [
    { pattern: "checkpoint_core/safety/**", rule: "Requires trusted human acceptor + passing safety_tests" },
    { pattern: "**/*.lock", rule: "Deny direct agent edits" },
    { pattern: "docs/**", rule: "Allow agent acceptance" },
  ],
  actor_rules: [
    { actor: "agent", rule: "May propose, may accept non-safety-critical paths" },
    { actor: "human (trusted)", rule: "May accept any path" },
    { actor: "ci", rule: "May verify, may not accept" },
  ],
  remote_rules: [
    "Remote objects are untrusted until locally re-verified",
    "Remote signatures are never auto-trusted",
  ],
  override_rules: [
    "Overrides require a trusted human identity",
    "All overrides are recorded in the audit log",
  ],
}

export const mockIdentities: Identity[] = [
  {
    name: "Jack Al-Kahwati",
    type: "human",
    fingerprint: "SHA256:9a4f2c1e8b7d3a05f6c9e2b1a8d7f4c30e1b2a9d",
    trust_status: "trusted",
    created_at: "2026-01-12T00:00:00Z",
    capabilities: ["accept", "sign", "override", "revoke"],
  },
  {
    name: "claude-code",
    type: "agent",
    fingerprint: "SHA256:1f0e9d8c7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e",
    trust_status: "untrusted",
    created_at: "2026-03-04T00:00:00Z",
    capabilities: ["propose", "verify"],
  },
  {
    name: "ci-runner",
    type: "ci",
    fingerprint: "SHA256:abc1230098deadbeef4455667788990011223344",
    trust_status: "trusted",
    created_at: "2026-02-20T00:00:00Z",
    capabilities: ["verify"],
  },
  {
    name: "legacy-bot",
    type: "machine",
    fingerprint: "SHA256:deadbeef0011223344556677889900aabbccddee",
    trust_status: "revoked",
    created_at: "2025-11-01T00:00:00Z",
    capabilities: [],
  },
]

export const mockAudit: AuditEvent[] = [
  {
    id: "a1",
    timestamp: "2026-06-22T08:40:30Z",
    actor: "claude-code",
    operation: "policy.check",
    result: "denied",
    policy_decision: "deny",
    ref_update: "feature/merge-rename",
  },
  {
    id: "a2",
    timestamp: "2026-06-21T15:05:11Z",
    actor: "Jack Al-Kahwati",
    operation: "push",
    result: "success",
    policy_decision: "allow",
    ref_update: "main → origin/main",
    server_receipt: "rcpt_4a91c7",
  },
  {
    id: "a3",
    timestamp: "2026-06-21T15:02:00Z",
    actor: "Jack Al-Kahwati",
    operation: "session.accept",
    result: "success",
    policy_decision: "allow",
    ref_update: "snap_9f2c41ab7d3e",
    server_receipt: "rcpt_4a90b2",
  },
  {
    id: "a4",
    timestamp: "2026-06-20T10:46:00Z",
    actor: "Jack Al-Kahwati",
    operation: "session.accept",
    result: "success",
    policy_decision: "allow",
    ref_update: "snap_c0ffee123456",
  },
  {
    id: "a5",
    timestamp: "2026-06-19T18:22:09Z",
    actor: "legacy-bot",
    operation: "identity.revoke",
    result: "success",
  },
]
