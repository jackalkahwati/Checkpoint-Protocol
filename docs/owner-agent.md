# Owner Agent

The **Owner Agent** reviews AI-produced work from your perspective and decides whether it can
be **auto-accepted/auto-merged** or must **escalate** to you. It is **deterministic** (rule-
based), bounded by your personal-autopilot config AND the policy engine — not an LLM.

## Builder vs Owner

- **Builder Agent** (e.g. Claude Code): writes code, edits files, snapshots, prepares the
  packet, may open an MR.
- **Owner Agent**: reviews task match, scope, changed paths, tests, policy, signatures,
  comments, conflicts, risk — then approves / auto-accepts / auto-merges / requests changes /
  escalates.

They are **separate identities**. The Builder cannot approve, accept, or merge its own work.

## What it checks → decision

Escalates (never auto-accepts) when any of: tests failed · policy denied · merge conflict ·
unresolved comments · a **protected path** was touched (e.g. `checkpoint_core/policy`,
`/sign`, `/remote`, `/server`, `/merge`, `src/auth`, `src/security`, `firmware/`,
`migrations/`) · change too large (> max files/deletions) · invalid signatures · the builder
is the owner agent.

Auto-accepts (low risk) only when **all** changed paths are within the configured allow-list
(default: `docs/`, `examples/`, `tests/`, `*.md`), tests pass (or none are configured), and
policy allows. Anything safe-but-outside the allow-list → **recommend manual** (not
auto-accepted).

## OwnerAgentReview record

Each review is ledgered and (when an identity exists) **signed** by the Owner Agent. Fields:
`review_id, target_type, target_id, owner_agent_identity_id, builder_agent_identity_id,
created_at, decision (approve|auto_accept|auto_merge|request_changes|reject|escalate|
no_decision), confidence, risk, reasoning, checked_items, verification_summary, changed_paths,
protected_paths_touched, unresolved_comments_count, conflict_count, signatures_status,
policy_effect, recommended_action, signed_review`.

## Security invariants (enforced)

- Owner Agent is a separate identity from the Builder; the Builder never self-approves.
- Owner Agent **cannot override or loosen policy** (policy denial always escalates).
- Owner Agent **cannot trust identities**.
- Auto-accept/auto-merge only when the config allow-rules **and** policy both permit.
- Cannot auto-merge failed tests, unresolved comments, conflicts, or unsigned/untrusted
  history when policy requires signatures.
- Reviews are ledgered and signed where possible.

Config lives in `.checkpoint/autopilot.yaml` (`checkpoint-core autopilot config`). Tighten or
loosen the allow-lists there; it starts conservative.
