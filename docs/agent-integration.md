# Agent Integration

Any AI coding agent can use Checkpoint to make its work **reviewable, recoverable, and
governed**. The contract is three phases. The key rule: **the agent produces work; a human
(or CI) accepts it.** Under the starter policy, agents cannot self-accept.

## The contract

**Before work** — open a session with agent metadata:
```bash
checkpoint-core agent begin "<instruction>" --agent <name> --model <model> --tool <tool>
# equivalently:
checkpoint-core start "<instruction>" --actor agent --agent <name> --model <model> --tool <tool>
```
Optionally run the autosave daemon so nothing is lost: `checkpoint-core watch &`.

**During work** — checkpoint meaningful steps and self-check:
```bash
checkpoint-core snapshot -m "extracted helper / passed unit step"
checkpoint-core verify
checkpoint-core policy check --operation accept        # is this allowed?
checkpoint-core agent status                            # what changed so far
```

**After work** — produce a packet for the human:
```bash
checkpoint-core agent packet        # instruction, diff, verification, policy, recommendation
# A HUMAN reviews (web UI or `show`) and runs:
checkpoint-core accept -m "<message>"     # signed by the human; policy-checked
```

If the agent made a mess: `checkpoint-core rollback --hard` restores the last accepted
state; autosaves remain for forensic recovery.

## Why this is safe
- Agents are first-class **identities** (`--type agent`); their authorship is recorded and
  signed, but the policy engine blocks agent self-accept by default.
- Every step is in the **session timeline** and the **ledger** — fully auditable.
- `verify` + `policy check` give the agent a deterministic go/no-go before asking a human.

## Sample prompts

**Claude Code / Codex / Cursor / OpenClaw·Hermes / generic agent** — add to the system prompt:

> You are working in a Checkpoint repository. At the start of a task run
> `checkpoint-core agent begin "<task>" --agent <you> --model <model> --tool <tool>`.
> After each meaningful step run `checkpoint-core snapshot -m "<what you did>"` and
> `checkpoint-core verify`. Before finishing run `checkpoint-core policy check --operation
> accept`; if it denies, fix the listed required actions. End with `checkpoint-core agent
> packet` and ask the human to review and `accept`. Never run `accept` yourself. If you
> break something, run `checkpoint-core rollback --hard`.

Tool-specific notes:
- **Claude Code / Codex**: run the commands via the shell tool; surface the `packet`
  summary back to the user for approval.
- **Cursor**: add the commands as tasks or a pre/post-edit hook; show the diff from
  `checkpoint-core diff` in the panel.
- **OpenClaw / Hermes / local agents**: wrap `agent begin` / `snapshot` / `verify` /
  `packet` around the edit loop; gate "done" on `policy check` returning allow.

## Hosted flow (optional)
Point the agent's repo at a hosted server so a human reviews in the browser:
```bash
checkpoint-core remote add origin http://host:8800/owner/repo --token <scoped-token>
checkpoint-core push origin main      # human reviews at http://host:8800/
```

This is intentionally **not** a heavy SDK — it's the existing CLI, used in a disciplined
order. That's enough to make AI work auditable today.
