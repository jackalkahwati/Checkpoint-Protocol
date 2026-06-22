# Checkpoint Hosted Service API

Version: 0.8 (MVP)
Transport: HTTP/1.1, JSON bodies, `application/octet-stream` for object/bundle payloads.
Server: standard-library `http.server` (no framework dependency, no Git).

> **The hosted service must not weaken the protocol.** The server never trusts the client
> and the client never blindly trusts the server. Both verify object hashes, schemas,
> snapshot seals, parent chains, reachability, signatures, and policy. **Refs only move
> after verification.** Private keys never cross the wire.

---

## Running

```bash
checkpoint-server init-store .checkpoint-server
checkpoint-server token create --store .checkpoint-server --name dev \
    --scopes repo:read,repo:write
checkpoint-server start --store .checkpoint-server --host 127.0.0.1 --port 8800
checkpoint-server doctor
```

Storage layout (`.checkpoint-server/`): `config.yaml` (server id + tokens),
`repos/<owner>/<repo>/` (each a full Checkpoint store under `.checkpoint/`, plus
`audit.jsonl`), `tmp/`, `locks/`.

## Authentication

API tokens, sent as `Authorization: Bearer <token>`. Tokens are stored **hashed**
(SHA-256); the plaintext is shown once at creation. A token has **scopes** and a
**repo_scope** (`owner/repo` or `*`).

Scopes: `repo:read`, `repo:write`, `refs:read`, `refs:write`, `objects:read`,
`objects:write`, `policy:read`, `policy:write`, `identity:read`, `identity:write`,
`admin`. `repo:write` implies the per-resource write scopes; `repo:read`/`repo:write`
imply the read scopes; `admin` implies everything. A token scoped to `owner/repo` is
rejected (403) on any other repo.

## Endpoints

### Health
- `GET /health` → `{status}`
- `GET /version` → `{api, protocol, server_id}`
- `GET /capabilities` → feature list

### Repos
- `POST /repos` `{owner, repo, branch?}` — create *(repo:write)*
- `GET /repos` → `{repos}` *(repo:read)*
- `GET /repos/{owner}/{repo}` → `{head, branches}` *(repo:read)*
- `DELETE /repos/{owner}/{repo}` *(admin)*

### Refs
- `GET …/refs` → `{heads, tags}` *(refs:read)*
- `GET …/refs/{ref}` → `{ref, target}` *(refs:read)*
- `POST …/refs/update` `{ref, old_target, new_target, force_with_lease?}` *(refs:write)* —
  verified ref update (closure → policy → fast-forward/lease → atomic write)

### Objects
- `GET …/objects/{id}` → raw bytes *(objects:read)*
- `POST …/objects/batch` *(objects:read to download, objects:write to upload)*
  - upload: `{objects:[{id, data_b64}]}` → `{stored, rejected}` (server verifies `sha256==id`)
  - download: `{get:[ids]}` → `{objects:[{id, data_b64}]}`
- `POST …/objects/verify` `{ids}` → presence + hash validity
- `GET …/objects/stats` → counts + bytes

### Sync
- `POST …/sync/plan` `{oids}` → `{missing}` (which ids the server lacks)
- `POST …/sync/push` `{branch, old_head, new_head, force_with_lease?, signatures, identities, sessions, uploaded}`
  → `{receipt}` (verify closure → policy → fast-forward/lease → atomic ref update)
- `POST …/sync/fetch` `{branch}` → `{head, oids, signatures, identities, sessions}`

### Bundles
- `POST …/bundles/import` (octet-stream `.tar.gz`) *(repo:write)* — verify (path-safety,
  hashes, seals, signatures, **reject private keys**) then import
- `GET …/bundles/export?branch=` → `.tar.gz` *(repo:read)*

### Sessions / diffs
- `GET …/sessions`, `GET …/sessions/{id}`, `…/{id}/timeline`, `…/{id}/packet`
- `POST …/diff` `{from, to}` → rename-aware DiffResult
- `POST …/merge-preview` `{ours, theirs}` → `{clean, conflicts, auto_merged, rename_records}`
  (does **not** mutate refs)

### Identities / signatures
- `GET …/identities`, `POST …/identities/import` `{identity}` (untrusted)
- `POST …/identities/{id}/trust|untrust|revoke` *(identity:write)*
- `GET …/signatures`, `POST …/verify-signatures`

### Policy
- `GET …/policy`, `PUT …/policy` `{policy}` *(policy:write, validated)*
- `POST …/policy/check` `{operation, …}` → PolicyDecision (**read-only**)
- `GET …/policy/decisions`, `GET …/policy/decisions/{id}`

### Integrity
- `POST …/fsck` → fsck report
- `POST …/gc` `{dry_run}` → gc report
- `GET …/audit` → audit log

## HTTP transfer protocol

1. Client asks for a **sync plan** (`sync/plan`) — server returns the object ids it lacks.
2. Client uploads only those objects (`objects/batch`); the server verifies each hash.
3. Client finalizes with `sync/push`; the server installs aux (signatures, public
   identities **untrusted**, sessions — no autosaves, no keys), **verifies the closure**,
   **evaluates policy**, checks **fast-forward / force-with-lease**, then **atomically**
   updates the ref under a **per-repo lock**.
4. The server returns a **ServerReceipt** which the client stores in its ledger:
   `{receipt_id, repo, operation, ref_updates, objects_received, policy_decision_ids,
   fsck_summary, created_at, server_identity_id, forced}`.

Fetch/clone reverse the flow: `sync/fetch` lists the closure + aux, the client downloads
missing objects (verifying every hash), installs aux, runs `verify_received`, and writes a
**remote-tracking** ref (`refs/remotes/<remote>/<branch>`); `pull` then fast-forwards.

## Client usage

```bash
checkpoint-core remote add origin http://host:8800/owner/repo --token <TOKEN>
checkpoint-core push origin main
checkpoint-core fetch origin
checkpoint-core pull origin main
checkpoint-core clone http://host:8800/owner/repo ./local --token <TOKEN>
checkpoint-core sync status origin
```

## Security guarantees

Reject: unauthenticated/over-scoped requests (401/403), malformed JSON (400), object
hash mismatch, refs to missing/non-snapshot objects, broken parent chains, invalid seals,
invalid signatures when required, policy violations (403), non-fast-forward without an
allowed lease (409), path traversal and private-key material in bundles (422). All
mutations are recorded in the per-repo audit log; writes are serialized by a per-repo lock
and applied atomically. Works with Git uninstalled; the Git bridge is never imported.
