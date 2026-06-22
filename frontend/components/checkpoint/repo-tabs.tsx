"use client"

import { useState } from "react"
import { GitBranch, Play, RotateCcw } from "lucide-react"

import { api } from "@/lib/checkpoint/api-client"
import { useApi } from "@/lib/checkpoint/use-api"
import { formatTime } from "@/lib/checkpoint/format"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Hash } from "@/components/checkpoint/hash"
import {
  IntegrityBadge,
  PolicyBadge,
  TrustBadge,
} from "@/components/checkpoint/badges"
import { LoadingState } from "@/components/checkpoint/states"

export function BranchesTab({ owner, repo }: { owner: string; repo: string }) {
  const { data, loading } = useApi(() => api.listBranches(owner, repo), [owner, repo])
  if (loading) return <LoadingState />
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow className="bg-secondary/40 hover:bg-secondary/40">
            <TableHead>Branch</TableHead>
            <TableHead>Accepted snapshot</TableHead>
            <TableHead>Last session</TableHead>
            <TableHead className="text-right">Ahead / behind</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(data ?? []).map((b) => (
            <TableRow key={b.name}>
              <TableCell>
                <span className="flex items-center gap-1.5 font-mono text-sm text-foreground">
                  <GitBranch className="size-3.5 text-muted-foreground" />
                  {b.name}
                </span>
              </TableCell>
              <TableCell>
                <Hash value={b.accepted_snapshot} len={12} />
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">{b.last_session ?? "—"}</TableCell>
              <TableCell className="text-right font-mono text-xs">
                <span className="text-success">+{b.ahead}</span>{" "}
                <span className="text-danger">-{b.behind}</span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function PolicyTab({ owner, repo }: { owner: string; repo: string }) {
  const config = useApi(() => api.getPolicy(owner, repo), [owner, repo])
  if (config.loading) return <LoadingState />
  const c = config.data
  if (!c) return null
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Card className="gap-0 py-0">
        <CardHeader className="border-b border-border px-4 py-3">
          <CardTitle className="text-sm">Protected branches</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-1.5 px-4 py-3">
          {c.protected_branches.map((b) => (
            <span key={b} className="rounded border border-border bg-muted px-1.5 py-px font-mono text-xs text-foreground">
              {b}
            </span>
          ))}
        </CardContent>
      </Card>

      <Card className="gap-0 py-0">
        <CardHeader className="border-b border-border px-4 py-3">
          <CardTitle className="text-sm">Remote rules</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-1.5 px-4 py-3 text-sm text-foreground">
          {c.remote_rules.map((r, i) => (
            <p key={i}>{r}</p>
          ))}
        </CardContent>
      </Card>

      <Card className="gap-0 py-0">
        <CardHeader className="border-b border-border px-4 py-3">
          <CardTitle className="text-sm">Path rules</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 px-4 py-3">
          {c.path_rules.map((r, i) => (
            <div key={i} className="flex flex-col gap-0.5">
              <code className="font-mono text-xs text-info">{r.pattern}</code>
              <span className="text-sm text-foreground">{r.rule}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="gap-0 py-0">
        <CardHeader className="border-b border-border px-4 py-3">
          <CardTitle className="text-sm">Actor rules</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 px-4 py-3">
          {c.actor_rules.map((r, i) => (
            <div key={i} className="flex flex-col gap-0.5">
              <span className="text-xs font-medium text-foreground">{r.actor}</span>
              <span className="text-sm text-muted-foreground">{r.rule}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="gap-0 py-0 md:col-span-2">
        <CardHeader className="border-b border-border px-4 py-3">
          <CardTitle className="text-sm">Override rules</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-1.5 px-4 py-3 text-sm text-foreground">
          {c.override_rules.map((r, i) => (
            <p key={i}>{r}</p>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

export function IdentitiesTab({ owner, repo }: { owner: string; repo: string }) {
  const { data, loading, isMock, reload } = useApi(() => api.listIdentities(owner, repo), [owner, repo])
  const [pending, setPending] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function act(id: string | undefined, op: "trust" | "untrust" | "revoke") {
    if (!id) return
    setErr(null)
    setPending(`${id}:${op}`)
    try {
      await api.setIdentityTrust(owner, repo, id, op)
      reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed.")
    } finally {
      setPending(null)
    }
  }

  if (loading) return <LoadingState />
  return (
    <div className="flex flex-col gap-2">
      {err ? <p className="text-sm text-destructive">{err}</p> : null}
      {isMock ? (
        <p className="text-xs text-muted-foreground">Mock data — trust actions are disabled.</p>
      ) : null}
      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow className="bg-secondary/40 hover:bg-secondary/40">
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Fingerprint</TableHead>
              <TableHead>Trust</TableHead>
              <TableHead>Capabilities</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data ?? []).map((id) => {
              const revoked = id.trust_status === "revoked"
              const trusted = id.trust_status === "trusted"
              const busy = pending?.startsWith(`${id.id}:`)
              return (
                <TableRow key={id.fingerprint}>
                  <TableCell className="font-medium text-foreground">{id.name}</TableCell>
                  <TableCell className="capitalize text-muted-foreground">{id.type}</TableCell>
                  <TableCell>
                    <Hash value={id.fingerprint} len={14} />
                  </TableCell>
                  <TableCell>
                    <TrustBadge trust={id.trust_status} />
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {id.capabilities.length === 0 ? (
                        <span className="text-xs text-muted-foreground">—</span>
                      ) : (
                        id.capabilities.map((cap) => (
                          <span
                            key={cap}
                            className="rounded border border-border bg-muted px-1.5 py-px font-mono text-[10px] text-muted-foreground"
                          >
                            {cap}
                          </span>
                        ))
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      {trusted ? (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={isMock || busy || !id.id}
                          onClick={() => act(id.id, "untrust")}
                        >
                          Untrust
                        </Button>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={isMock || busy || revoked || !id.id}
                          onClick={() => act(id.id, "trust")}
                        >
                          Trust
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={isMock || busy || revoked || !id.id}
                        onClick={() => act(id.id, "revoke")}
                      >
                        Revoke
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

export function IntegrityTab({ owner, repo }: { owner: string; repo: string }) {
  const { data, loading, isMock, reload } = useApi(() => api.getIntegrity(owner, repo), [owner, repo])
  if (loading) return <LoadingState />
  const i = data
  if (!i) return null
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Object store</span>
          <IntegrityBadge status={i.fsck_status} />
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={reload} disabled={isMock}>
            <Play data-icon="inline-start" />
            Run fsck
          </Button>
          <Button variant="outline" size="sm" disabled={isMock}>
            <RotateCcw data-icon="inline-start" />
            GC dry run
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Objects" value={i.object_count.toLocaleString()} />
        <Stat label="Dangling" value={String(i.dangling_count)} tone={i.dangling_count > 0 ? "warning" : undefined} />
        <Stat label="Corrupt" value={String(i.corrupt_count)} tone={i.corrupt_count > 0 ? "danger" : undefined} />
        <Stat label="Missing" value={String(i.missing_count)} tone={i.missing_count > 0 ? "danger" : undefined} />
      </div>
      <Card className="gap-0 py-0">
        <CardContent className="flex flex-col gap-1 px-4 py-3 text-sm">
          <span className="text-xs text-muted-foreground">Seal status</span>
          <span className="capitalize text-foreground">{i.seal_status}</span>
          <span className="mt-2 text-xs text-muted-foreground">Last GC result</span>
          <span className="text-foreground">{i.last_gc_result}</span>
        </CardContent>
      </Card>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "warning" | "danger" }) {
  return (
    <Card className="gap-0 py-0">
      <CardContent className="flex flex-col gap-1 px-4 py-3">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span
          className={
            tone === "danger"
              ? "font-mono text-lg text-danger"
              : tone === "warning"
                ? "font-mono text-lg text-warning"
                : "font-mono text-lg text-foreground"
          }
        >
          {value}
        </span>
      </CardContent>
    </Card>
  )
}

export function AuditTab({ owner, repo }: { owner: string; repo: string }) {
  const { data, loading } = useApi(() => api.getAudit(owner, repo), [owner, repo])
  if (loading) return <LoadingState />
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow className="bg-secondary/40 hover:bg-secondary/40">
            <TableHead>Timestamp</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Operation</TableHead>
            <TableHead>Result</TableHead>
            <TableHead>Policy</TableHead>
            <TableHead>Ref update</TableHead>
            <TableHead className="text-right">Receipt</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(data ?? []).map((e) => (
            <TableRow key={e.id}>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{formatTime(e.timestamp)}</TableCell>
              <TableCell className="text-sm text-foreground">{e.actor}</TableCell>
              <TableCell>
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">{e.operation}</code>
              </TableCell>
              <TableCell>
                <span
                  className={
                    e.result === "success"
                      ? "text-xs text-success"
                      : e.result === "denied"
                        ? "text-xs text-danger"
                        : "text-xs text-warning"
                  }
                >
                  {e.result}
                </span>
              </TableCell>
              <TableCell>{e.policy_decision ? <PolicyBadge effect={e.policy_decision} /> : <span className="text-xs text-muted-foreground">—</span>}</TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">{e.ref_update ?? "—"}</TableCell>
              <TableCell className="text-right">
                {e.server_receipt ? <Hash value={e.server_receipt} len={10} /> : <span className="text-xs text-muted-foreground">—</span>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
