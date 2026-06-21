# Example workflow

A complete walkthrough you can copy/paste. It mirrors the canonical Checkpoint flow:
init → start → edit → snapshot → diff → verify → packet → accept (or rollback).

The runnable version of this is `examples/demo.sh`.

---

## 1. Set up a repo

```bash
mkdir camera-demo && cd camera-demo
git init
printf "exposure: auto\nfps: 30\n" > camera.yaml
printf "def drive():\n    pass\n" > autonomy.py
git add -A && git commit -m "initial"
```

## 2. Initialize Checkpoint

```bash
checkpoint init
```

Creates `.checkpoint/`, a default `config.yaml`, a `.checkpointignore`, and adds
`.checkpoint/` to `.gitignore`.

Add a verification command so `verify` does something real:

```bash
cat >> .checkpoint/config.yaml <<'YAML'
YAML
# (or edit .checkpoint/config.yaml and set verification.commands)
```

Example `verification` block:

```yaml
verification:
  run_on_accept: true
  commands:
    - name: syntax
      run: python -m py_compile autonomy.py
```

## 3. Start a session

```bash
checkpoint start "fix camera exposure defaults without changing autonomy behavior" --tag hardware
```

Checkpoint records the branch, HEAD, and a baseline tree of the working directory.

## 4. Do the work (human or AI)

```bash
printf "exposure: 1/500\nfps: 30\n" > camera.yaml
```

## 5. Snapshot a meaningful state

```bash
checkpoint snapshot --message "camera config updated"
```

## 6. Review what changed

```bash
checkpoint status
checkpoint diff --summary
checkpoint diff            # full unified diff from session start
```

## 7. Verify

```bash
checkpoint verify
```

Runs the configured commands and stores results.

## 8. Generate the Change Packet

```bash
checkpoint packet
```

Prints the instruction, branch, base commit, changed files, snapshots, verification
status, risks, a recommended commit message, and a recommended next action. Saved to
`.checkpoint/sessions/<id>/packet.json`.

## 9a. Accept the work

```bash
checkpoint accept --message "fix camera exposure defaults"
git log --oneline      # one clean commit, .checkpoint not included
```

## 9b. ...or roll it back

If the change was wrong:

```bash
checkpoint rollback            # preview (safe)
checkpoint rollback --hard     # restore to session start; a pre-rollback snapshot is taken first
cat camera.yaml                # back to the original
```

## 10. Audit later

```bash
checkpoint log
checkpoint show <session-id>
checkpoint export <session-id> --out session.tar.gz
```

---

## AI-agent variant

Agents pass their identity so the work is fully traceable:

```bash
checkpoint start "refactor the planner for clarity" \
  --agent claude-code --model opus-4.8 --tool Edit --tag refactor

# agent edits files, runs commands ...

checkpoint snapshot --message "extracted planner helpers"
checkpoint verify
checkpoint packet
# A human reviews the packet, then:
checkpoint accept
```

For `--tag safety-critical`, the default risk rules force verification, forbid an agent
from self-accepting (a human must run accept), and require a conflict-free working tree.
