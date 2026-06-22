"use client"

import { useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import {
  AlertTriangle,
  CheckCircle2,
  GitMerge,
  MessageSquare,
  XCircle,
} from "lucide-react"

import { api } from "@/lib/checkpoint/api-client"
import { useApi } from "@/lib/checkpoint/use-api"
import { formatTime } from "@/lib/checkpoint/format"
import type { MergeRequestDetail, ReviewStatus, Session } from "@/lib/checkpoint/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Pill, PolicyBadge } from "@/components/checkpoint/badges"
import { DiffViewer } from "@/components/checkpoint/diff-viewer"
import { Hash } from "@/components/checkpoint/hash"
import { ErrorState, LoadingState } from "@/components/checkpoint/states"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

function statusPill(status: ReviewStatus) {
  const c = {
    open: { tone: "info" as const, label: "Open" },
    merged: { tone: "success" as const, label: "Merged" },
    closed: { tone: "neutral" as const, label: "Closed" },
  }[status]
  return <Pill tone={c.tone}>{c.label}</Pill>
}

export function ReviewsTab({ owner, repo }: { owner: string; repo: string }) {
  const router = useRouter()
  const { data, loading, error, isMock, reload } = useApi(() => api.listReviews(owner, repo), [owner, repo])
  const sessionsQuery = useApi(() => api.listSessions(owner, repo), [owner, repo])
  const [open, setOpen] = useState(false)

  if (loading) return <LoadingState />
  if (error) return <ErrorState title="Could not load merge requests" message={error} />

  const accepted = (sessionsQuery.data ?? []).filter((s: Session) => s.accepted_snapshot)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Propose merging a reviewed session into a branch. Review, comment, then merge.
        </p>
        <Button size="sm" onClick={() => setOpen((v) => !v)} disabled={isMock}>
          <GitMerge data-icon="inline-start" />
          New merge request
        </Button>
      </div>

      {open ? (
        <NewReviewForm
          owner={owner}
          repo={repo}
          sessions={accepted}
          onCreated={(id) => {
            setOpen(false)
            reload()
            router.push(`/repos/${owner}/${repo}/reviews/${id}`)
          }}
        />
      ) : null}

      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow className="bg-secondary/40 hover:bg-secondary/40">
              <TableHead>Merge request</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Into</TableHead>
              <TableHead className="text-right">Comments</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-sm text-muted-foreground">
                  No merge requests yet.
                </TableCell>
              </TableRow>
            ) : (
              (data ?? []).map((mr) => (
                <TableRow
                  key={mr.id}
                  className="cursor-pointer"
                  onClick={() => router.push(`/repos/${owner}/${repo}/reviews/${mr.id}`)}
                >
                  <TableCell>
                    <span className="font-medium text-foreground">{mr.title}</span>
                    <span className="ml-2 font-mono text-xs text-muted-foreground">{mr.id}</span>
                  </TableCell>
                  <TableCell>{statusPill(mr.status)}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{mr.target_branch}</TableCell>
                  <TableCell className="text-right text-sm text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <MessageSquare className="size-3.5" />
                      {mr.comment_count}
                      {mr.unresolved_count > 0 ? (
                        <span className="text-warning"> ({mr.unresolved_count} open)</span>
                      ) : null}
                    </span>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function NewReviewForm({
  owner,
  repo,
  sessions,
  onCreated,
}: {
  owner: string
  repo: string
  sessions: Session[]
  onCreated: (id: string) => void
}) {
  const [title, setTitle] = useState("")
  const [sessionId, setSessionId] = useState(sessions[0]?.session_id ?? "")
  const [target, setTarget] = useState("main")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit() {
    setErr(null)
    setBusy(true)
    try {
      const { data } = await api.createReview(owner, repo, {
        title,
        source_session: sessionId,
        target_branch: target,
      })
      if (data?.id) onCreated(data.id)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to create.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <div className="grid gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1 md:col-span-2">
          <span className="text-xs text-muted-foreground">Title</span>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What this merges" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Into branch</span>
          <Input value={target} onChange={(e) => setTarget(e.target.value)} />
        </label>
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">Source session (accepted)</span>
        <select
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
        >
          {sessions.length === 0 ? <option value="">No accepted sessions</option> : null}
          {sessions.map((s) => (
            <option key={s.session_id} value={s.session_id}>
              {s.instruction.slice(0, 70)} — {s.session_id.slice(0, 16)}
            </option>
          ))}
        </select>
      </label>
      {err ? <p className="text-sm text-destructive">{err}</p> : null}
      <div className="flex justify-end">
        <Button size="sm" onClick={submit} disabled={busy || !title || !sessionId}>
          Create merge request
        </Button>
      </div>
    </div>
  )
}

export function ReviewDetail({ owner, repo, id }: { owner: string; repo: string; id: string }) {
  const { data, loading, error, reload } = useApi(() => api.getReview(owner, repo, id), [owner, repo, id])
  const [actionErr, setActionErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  if (loading) return <LoadingState label="Loading merge request…" />
  if (error) return <ErrorState title="Could not load merge request" message={error} />
  const mr = data as MergeRequestDetail
  if (!mr?.id) return <ErrorState title="Not found" message="No such merge request." />

  async function act(kind: "merge" | "close" | "approve", fn: () => Promise<unknown>) {
    setActionErr(null)
    setBusy(kind)
    try {
      const res = (await fn()) as { data?: { status?: string; reasons?: string[]; conflicts?: string[] } }
      const r = res?.data
      if (r && r.status && r.status !== "merged" && r.status !== "closed" && r.status !== "open") {
        const detail =
          r.reasons?.join("; ") || (r.conflicts?.length ? `conflicts in ${r.conflicts.join(", ")}` : r.status)
        setActionErr(`Merge ${r.status}: ${detail}`)
      }
      reload()
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : "Action failed.")
    } finally {
      setBusy(null)
    }
  }

  const m = mr.mergeability

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">{mr.title}</h1>
          {statusPill(mr.status)}
          <span className="font-mono text-xs text-muted-foreground">{mr.id}</span>
        </div>
        <p className="text-sm text-muted-foreground">
          Merging <Hash value={mr.source_snapshot} len={10} /> into{" "}
          <span className="font-mono text-foreground">{mr.target_branch}</span>
          {mr.source_session ? <span className="ml-1">· session {mr.source_session.slice(0, 18)}</span> : null}
        </p>
      </div>

      {/* mergeability banner */}
      {mr.status === "merged" ? (
        <Banner tone="ok" icon={CheckCircle2}>Merged into {mr.target_branch}.</Banner>
      ) : mr.status === "closed" ? (
        <Banner tone="muted" icon={XCircle}>This merge request was closed without merging.</Banner>
      ) : m.clean ? (
        <Banner tone="ok" icon={CheckCircle2}>
          No conflicts{m.fast_forward ? " (fast-forward)" : ""}. Ready to merge.
        </Banner>
      ) : (
        <Banner tone="bad" icon={AlertTriangle}>
          Conflicts in {m.conflicts.length} file(s): <span className="font-mono">{m.conflicts.join(", ")}</span>.
          Resolve locally (<code>checkpoint-core merge</code>) and push, then refresh.
        </Banner>
      )}

      {/* policy + approvals + actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Policy:</span>
            {mr.policy ? <PolicyBadge effect={mr.policy.effect} /> : <span className="text-muted-foreground">none</span>}
          </span>
          <span className="flex items-center gap-1.5">
            <CheckCircle2 className={`size-4 ${mr.approval_count > 0 ? "text-success" : "text-muted-foreground"}`} />
            <span className="text-muted-foreground">
              {mr.approval_count} approval{mr.approval_count === 1 ? "" : "s"}
              {mr.approvals.length ? <span className="ml-1 text-foreground">({mr.approvals.join(", ")})</span> : null}
            </span>
          </span>
          {mr.policy && mr.policy.effect === "deny" ? (
            <span className="text-xs text-destructive">{mr.policy.reasons.join("; ")}</span>
          ) : null}
        </div>
        <div className="flex gap-2">
          {mr.status === "open" ? (
            <>
              <Button size="sm" variant="outline" disabled={busy !== null}
                onClick={() => act("approve", () => api.approveReview(owner, repo, id, true))}>
                <CheckCircle2 data-icon="inline-start" />
                Approve
              </Button>
              {mr.approval_count > 0 ? (
                <Button size="sm" variant="ghost" disabled={busy !== null}
                  onClick={() => act("approve", () => api.approveReview(owner, repo, id, false))}>
                  Remove approval
                </Button>
              ) : null}
              <Button size="sm" disabled={!mr.mergeable || busy !== null} onClick={() => act("merge", () => api.mergeReview(owner, repo, id))}>
                <GitMerge data-icon="inline-start" />
                {busy === "merge" ? "Merging…" : "Merge"}
              </Button>
              <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => act("close", () => api.closeReview(owner, repo, id))}>
                Close
              </Button>
            </>
          ) : null}
        </div>
      </div>
      {actionErr ? <p className="text-sm text-destructive">{actionErr}</p> : null}

      {/* diff with inline line comments */}
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">Changes</h2>
        <DiffViewer
          files={mr.diff ?? []}
          review={{
            comments: mr.comments,
            onAddComment: async (path, line, body) => {
              await api.addReviewComment(owner, repo, id, { body, path, line })
              reload()
            },
            onResolve: async (cid, resolved) => {
              await api.resolveReviewComment(owner, repo, id, cid, resolved)
              reload()
            },
          }}
        />
      </section>

      {/* comments */}
      <CommentThread owner={owner} repo={repo} id={id} mr={mr} onChange={reload} />
    </div>
  )
}

function Banner({
  tone,
  icon: Icon,
  children,
}: {
  tone: "ok" | "bad" | "muted"
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  const cls = {
    ok: "border-success/30 bg-success-muted/20 text-foreground",
    bad: "border-destructive/30 bg-destructive/10 text-foreground",
    muted: "border-border bg-muted/30 text-muted-foreground",
  }[tone]
  return (
    <div className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${cls}`}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div>{children}</div>
    </div>
  )
}

function CommentThread({
  owner,
  repo,
  id,
  mr,
  onChange,
}: {
  owner: string
  repo: string
  id: string
  mr: MergeRequestDetail
  onChange: () => void
}) {
  const [body, setBody] = useState("")
  const [path, setPath] = useState("")
  const [busy, setBusy] = useState(false)

  async function add() {
    if (!body.trim()) return
    setBusy(true)
    try {
      await api.addReviewComment(owner, repo, id, { body, path: path || null })
      setBody("")
      setPath("")
      onChange()
    } finally {
      setBusy(false)
    }
  }

  async function toggle(cid: string, resolved: boolean) {
    await api.resolveReviewComment(owner, repo, id, cid, resolved)
    onChange()
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-foreground">
        Review thread{mr.comments.length ? ` (${mr.comments.length})` : ""}
      </h2>
      <div className="flex flex-col gap-2">
        {mr.comments.length === 0 ? (
          <p className="text-sm text-muted-foreground">No comments yet.</p>
        ) : (
          mr.comments.map((c) => (
            <div key={c.id} className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{c.author}</span>
                  {c.path ? <span className="font-mono">{c.path}{c.line ? `:${c.line}` : ""}</span> : null}
                  <span>{formatTime(c.created_at)}</span>
                  {c.resolved ? <Pill tone="success">resolved</Pill> : null}
                </div>
                <Button size="sm" variant="ghost" onClick={() => toggle(c.id, !c.resolved)}>
                  {c.resolved ? "Reopen" : "Resolve"}
                </Button>
              </div>
              <p className="mt-1.5 whitespace-pre-wrap text-sm text-foreground">{c.body}</p>
            </div>
          ))
        )}
      </div>
      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
        <Textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Leave a comment…"
          rows={3}
        />
        <div className="flex items-center gap-2">
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="optional file path (e.g. src/app.py)"
            className="max-w-xs"
          />
          <div className="flex-1" />
          <Button size="sm" onClick={add} disabled={busy || !body.trim()}>
            Comment
          </Button>
        </div>
      </div>
    </section>
  )
}
