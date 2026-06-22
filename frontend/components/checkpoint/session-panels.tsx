"use client"

import {
  ArrowRight,
  Check,
  CheckCircle2,
  FileCheck2,
  Fingerprint,
  GitMerge,
  RotateCcw,
  ShieldCheck,
  Terminal,
  TestTube2,
  X,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"
import { formatDuration, formatTime } from "@/lib/checkpoint/format"
import type {
  Integrity,
  PolicyDecision,
  Signature,
  VerificationResult,
} from "@/lib/checkpoint/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { IntegrityBadge, PolicyBadge, SignatureBadge, VerificationBadge } from "@/components/checkpoint/badges"

function Panel({
  title,
  icon: Icon,
  action,
  children,
}: {
  title: string
  icon: LucideIcon
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-border px-4 py-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Icon className="size-4 text-muted-foreground" />
          {title}
        </CardTitle>
        {action}
      </CardHeader>
      <CardContent className="px-4 py-3 text-sm">{children}</CardContent>
    </Card>
  )
}

export function PolicyPanel({ decision }: { decision: PolicyDecision | null }) {
  return (
    <Panel
      title="Policy Decision"
      icon={ShieldCheck}
      action={decision ? <PolicyBadge effect={decision.effect} /> : null}
    >
      {!decision ? (
        <p className="text-muted-foreground">No policy decision recorded.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted-foreground">Whether this operation is allowed.</p>
          <div className="flex flex-col gap-1">
            {decision.reasons.map((r, i) => (
              <p key={i} className="text-sm text-foreground">
                {r}
              </p>
            ))}
          </div>

          {decision.required_actions.length > 0 ? (
            <div className="rounded-md border border-danger/25 bg-danger-muted/50 p-2.5">
              <p className="mb-1.5 text-xs font-semibold tracking-wide text-danger uppercase">Required actions</p>
              <ul className="flex flex-col gap-1.5">
                {decision.required_actions.map((a, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                    <ArrowRight className="mt-0.5 size-3.5 shrink-0 text-danger" />
                    {a}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {decision.matched_rules.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {decision.matched_rules.map((rule) => (
                <span
                  key={rule}
                  className="rounded border border-border bg-muted px-1.5 py-px font-mono text-[11px] text-muted-foreground"
                >
                  {rule}
                </span>
              ))}
            </div>
          ) : null}

          <p className="text-xs text-muted-foreground">
            Override {decision.override_available ? "available" : "unavailable"}
            {decision.override_used ? " · override used" : ""}
          </p>
        </div>
      )}
    </Panel>
  )
}

export function VerificationPanel({ results }: { results: VerificationResult[] }) {
  return (
    <Panel
      title="Verification"
      icon={TestTube2}
      action={results[0] ? <VerificationBadge status={results[0].status} /> : null}
    >
      {results.length === 0 ? (
        <p className="text-muted-foreground">No verification runs.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {results.map((r, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              {i > 0 ? <Separator /> : null}
              <div className="flex items-center justify-between gap-2">
                <code className="truncate rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">
                  {r.command}
                </code>
                <VerificationBadge status={r.status} />
              </div>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{r.summary}</span>
                <span>{formatDuration(r.duration_ms)}</span>
              </div>
              {r.stderr_excerpt ? (
                <pre className="mt-1 overflow-x-auto rounded-md border border-danger/20 bg-danger-muted/40 p-2 font-mono text-[11px] leading-relaxed text-danger">
                  {r.stderr_excerpt}
                </pre>
              ) : null}
              {r.stdout_excerpt && !r.stderr_excerpt ? (
                <pre className="mt-1 overflow-x-auto rounded-md border border-border bg-muted/50 p-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
                  {r.stdout_excerpt}
                </pre>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

export function SignaturePanel({ signatures }: { signatures: Signature[] }) {
  const primary = signatures[0]
  return (
    <Panel
      title="Signatures & Trust"
      icon={Fingerprint}
      action={primary ? <SignatureBadge status={primary.status} trust={primary.trust_status} /> : null}
    >
      <p className="mb-2 text-xs text-muted-foreground">Proof of who accepted or signed the work.</p>
      {signatures.length === 0 ? (
        <p className="text-muted-foreground">No signatures.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {signatures.map((s, i) => (
            <div key={i} className="flex flex-col gap-1.5 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{s.signer_name}</span>
                <SignatureBadge status={s.status} trust={s.trust_status} />
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Signer type</dt>
                <dd className="text-foreground">{s.signer_type}</dd>
                <dt className="text-muted-foreground">Trust</dt>
                <dd className="text-foreground capitalize">{s.trust_status}</dd>
                <dt className="text-muted-foreground">Validity</dt>
                <dd className="text-foreground capitalize">{s.status}</dd>
                {s.signed_at ? (
                  <>
                    <dt className="text-muted-foreground">Signed</dt>
                    <dd className="text-foreground">{formatTime(s.signed_at)}</dd>
                  </>
                ) : null}
                {s.fingerprint ? (
                  <>
                    <dt className="text-muted-foreground">Fingerprint</dt>
                    <dd className="truncate font-mono text-muted-foreground">{s.fingerprint}</dd>
                  </>
                ) : null}
              </dl>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

export function IntegrityPanel({ integrity }: { integrity: Integrity | null }) {
  return (
    <Panel
      title="Integrity"
      icon={ShieldCheck}
      action={integrity ? <IntegrityBadge status={integrity.fsck_status} /> : null}
    >
      {!integrity ? (
        <p className="text-muted-foreground">No integrity data.</p>
      ) : (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">fsck</dt>
          <dd className="text-right capitalize text-foreground">{integrity.fsck_status}</dd>
          <dt className="text-muted-foreground">Seal</dt>
          <dd className="text-right capitalize text-foreground">{integrity.seal_status}</dd>
          <dt className="text-muted-foreground">Objects</dt>
          <dd className="text-right font-mono text-foreground">{integrity.object_count.toLocaleString()}</dd>
          <dt className="text-muted-foreground">Dangling</dt>
          <dd className={cn("text-right font-mono", integrity.dangling_count > 0 ? "text-warning" : "text-foreground")}>
            {integrity.dangling_count}
          </dd>
          <dt className="text-muted-foreground">Missing</dt>
          <dd className={cn("text-right font-mono", integrity.missing_count > 0 ? "text-danger" : "text-foreground")}>
            {integrity.missing_count}
          </dd>
          <dt className="text-muted-foreground">Corrupt</dt>
          <dd className={cn("text-right font-mono", integrity.corrupt_count > 0 ? "text-danger" : "text-foreground")}>
            {integrity.corrupt_count}
          </dd>
        </dl>
      )}
    </Panel>
  )
}

interface ActionConfig {
  key: string
  label: string
  icon: LucideIcon
  cli: string
  variant?: "default" | "outline" | "destructive" | "secondary"
}

const actions: ActionConfig[] = [
  { key: "policy", label: "Run policy check", icon: ShieldCheck, cli: "checkpoint-core policy check", variant: "outline" },
  { key: "verify", label: "Verify signatures", icon: Fingerprint, cli: "checkpoint-core sig verify", variant: "outline" },
  { key: "fsck", label: "Run fsck", icon: FileCheck2, cli: "checkpoint-core fsck", variant: "outline" },
  { key: "merge", label: "Merge preview", icon: GitMerge, cli: "checkpoint-core merge --preview", variant: "outline" },
  { key: "accept", label: "Accept", icon: Check, cli: "checkpoint-core accept", variant: "default" },
  { key: "reject", label: "Reject", icon: X, cli: "checkpoint-core reject", variant: "destructive" },
  { key: "rollback", label: "Rollback", icon: RotateCcw, cli: "checkpoint-core rollback", variant: "secondary" },
]

export function ActionsPanel({ live }: { live: boolean }) {
  return (
    <Panel title="Review Actions" icon={CheckCircle2}>
      <div className="flex flex-col gap-2">
        {!live ? (
          <div className="flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted/40 p-2 text-xs text-warning">
            <Terminal className="mt-0.5 size-3.5 shrink-0" />
            <span>
              Action endpoints unavailable. Run these from the CLI — buttons show the equivalent command.
            </span>
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-2">
          {actions.map((a) => {
            const Icon = a.icon
            const wide = a.key === "accept" || a.key === "reject"
            return (
              <div key={a.key} className={cn("flex flex-col gap-1", wide && "col-span-1")}>
                <Button variant={a.variant} size="sm" disabled={!live} className="w-full justify-start">
                  <Icon data-icon="inline-start" />
                  {a.label}
                </Button>
                {!live ? (
                  <code className="truncate rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {a.cli}
                  </code>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
    </Panel>
  )
}
