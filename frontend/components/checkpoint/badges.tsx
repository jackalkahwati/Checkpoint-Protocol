"use client"

import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  Cpu,
  GitMerge,
  Server,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  SkipForward,
  User,
  XCircle,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type {
  ActorType,
  FsckStatus,
  PolicyEffect,
  SessionStatus,
  SignatureValidity,
  TrustStatus,
  VerificationStatus,
} from "@/lib/checkpoint/types"

type Tone = "success" | "warning" | "danger" | "info" | "neutral"

const toneClass: Record<Tone, string> = {
  success: "bg-success-muted text-success border-success/25",
  warning: "bg-warning-muted text-warning border-warning/25",
  danger: "bg-danger-muted text-danger border-danger/25",
  info: "bg-info-muted text-info border-info/25",
  neutral: "bg-muted text-muted-foreground border-border",
}

interface PillProps {
  tone: Tone
  icon?: LucideIcon
  children: ReactNode
  tip?: ReactNode
  className?: string
  mono?: boolean
}

export function Pill({ tone, icon: Icon, children, tip, className, mono }: PillProps) {
  const pill = (
    <span
      className={cn(
        "inline-flex h-5 w-fit shrink-0 items-center gap-1 rounded-md border px-1.5 text-xs font-medium whitespace-nowrap",
        mono && "font-mono",
        toneClass[tone],
        className,
      )}
    >
      {Icon ? <Icon className="size-3 shrink-0" /> : null}
      {children}
    </span>
  )
  if (!tip) return pill
  return (
    <Tooltip>
      <TooltipTrigger render={<span className="inline-flex" />}>{pill}</TooltipTrigger>
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
  )
}

export function StatusBadge({ status }: { status: SessionStatus }) {
  const map: Record<string, { tone: Tone; icon: LucideIcon; label: string; tip: string }> = {
    active: { tone: "info", icon: CircleDashed, label: "Active", tip: "Session is in progress" },
    accepted: { tone: "success", icon: CheckCircle2, label: "Accepted", tip: "Reviewed and added to accepted history" },
    rejected: { tone: "danger", icon: XCircle, label: "Rejected", tip: "Session was rejected" },
    rolled_back: { tone: "warning", icon: CircleDashed, label: "Rolled back", tip: "Session was rolled back" },
    abandoned: { tone: "neutral", icon: CircleDashed, label: "Abandoned", tip: "Superseded session, cleaned up by prune" },
    merged: { tone: "info", icon: GitMerge, label: "Merged", tip: "Session was merged" },
  }
  // Never let an unknown status white-screen the repo — fall back to a neutral pill.
  const c = map[status] ?? { tone: "neutral" as Tone, icon: CircleDashed, label: String(status), tip: "Unknown status" }
  return (
    <Pill tone={c.tone} icon={c.icon} tip={c.tip}>
      {c.label}
    </Pill>
  )
}

export function PolicyBadge({ effect }: { effect: PolicyEffect }) {
  const map: Record<PolicyEffect, { tone: Tone; icon: LucideIcon; label: string; tip: string }> = {
    allow: { tone: "success", icon: ShieldCheck, label: "Allow", tip: "Policy allows this operation" },
    warn: { tone: "warning", icon: ShieldAlert, label: "Warn", tip: "Policy warning on this operation" },
    deny: { tone: "danger", icon: ShieldX, label: "Deny", tip: "Policy denies this operation" },
  }
  const c = map[effect]
  return (
    <Pill tone={c.tone} icon={c.icon} tip={c.tip}>
      {c.label}
    </Pill>
  )
}

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  const map: Record<VerificationStatus, { tone: Tone; icon: LucideIcon; label: string; tip: string }> = {
    passed: { tone: "success", icon: CheckCircle2, label: "Verified", tip: "Verification passed" },
    failed: { tone: "danger", icon: XCircle, label: "Failed", tip: "Verification failed" },
    skipped: { tone: "neutral", icon: SkipForward, label: "Skipped", tip: "Verification skipped" },
  }
  const c = map[status]
  return (
    <Pill tone={c.tone} icon={c.icon} tip={c.tip}>
      {c.label}
    </Pill>
  )
}

export function SignatureBadge({
  status,
  trust,
}: {
  status: SignatureValidity
  trust?: TrustStatus
}) {
  if (status === "unsigned") {
    return (
      <Pill tone="warning" icon={ShieldAlert} tip="No signature on this work">
        Unsigned
      </Pill>
    )
  }
  if (status === "invalid") {
    return (
      <Pill tone="danger" icon={ShieldX} tip="Signature is invalid">
        Invalid
      </Pill>
    )
  }
  const tone: Tone = trust === "trusted" ? "success" : trust === "revoked" ? "danger" : "warning"
  return (
    <Pill tone={tone} icon={ShieldCheck} tip={`Signed (${trust ?? "unknown"} signer)`}>
      Signed
    </Pill>
  )
}

export function TrustBadge({ trust }: { trust: TrustStatus }) {
  const map: Record<TrustStatus, { tone: Tone; icon: LucideIcon; label: string; tip: string }> = {
    trusted: { tone: "success", icon: ShieldCheck, label: "Trusted", tip: "Trusted identity" },
    untrusted: { tone: "warning", icon: ShieldAlert, label: "Untrusted", tip: "Untrusted identity" },
    unknown: { tone: "neutral", icon: CircleHelp, label: "Unknown", tip: "Unknown identity" },
    revoked: { tone: "danger", icon: ShieldX, label: "Revoked", tip: "Revoked identity" },
  }
  const c = map[trust]
  return (
    <Pill tone={c.tone} icon={c.icon} tip={c.tip}>
      {c.label}
    </Pill>
  )
}

export function IntegrityBadge({ status }: { status: FsckStatus }) {
  const map: Record<FsckStatus, { tone: Tone; icon: LucideIcon; label: string; tip: string }> = {
    healthy: { tone: "success", icon: ShieldCheck, label: "Healthy", tip: "Object store is healthy" },
    warnings: { tone: "warning", icon: AlertTriangle, label: "Warnings", tip: "Object store has warnings" },
    corrupt: { tone: "danger", icon: ShieldX, label: "Corrupt", tip: "Object store is corrupt" },
  }
  const c = map[status]
  return (
    <Pill tone={c.tone} icon={c.icon} tip={c.tip}>
      {c.label}
    </Pill>
  )
}

const actorIcon: Record<ActorType, LucideIcon> = {
  human: User,
  agent: Bot,
  ci: Server,
  machine: Cpu,
  service: Server,
}

export function ActorBadge({ name, type }: { name: string; type: ActorType }) {
  const Icon = actorIcon[type]
  return (
    <Pill tone="info" icon={Icon} tip={`${type} identity`}>
      {name}
    </Pill>
  )
}

export function MockBadge() {
  return (
    <Pill tone="warning" icon={CircleDashed} tip="Backend unavailable — showing mock data">
      Mock data
    </Pill>
  )
}
