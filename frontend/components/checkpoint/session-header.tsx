"use client"

import { GitBranch } from "lucide-react"

import { formatTime } from "@/lib/checkpoint/format"
import type { Session } from "@/lib/checkpoint/types"
import { Hash } from "@/components/checkpoint/hash"
import {
  ActorBadge,
  IntegrityBadge,
  MockBadge,
  Pill,
  PolicyBadge,
  SignatureBadge,
  StatusBadge,
  VerificationBadge,
} from "@/components/checkpoint/badges"

export function SessionHeader({ session, isMock }: { session: Session; isMock?: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Session</p>
          <h1 className="text-pretty text-xl font-semibold tracking-tight text-foreground md:text-2xl">
            {session.instruction}
          </h1>
        </div>
        {isMock ? <MockBadge /> : null}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge status={session.status} />
        <ActorBadge name={session.actor_identity} type={session.actor_type} />
        <Pill tone="neutral" icon={GitBranch} mono>
          {session.branch}
        </Pill>
        <VerificationBadge status={session.verification_status} />
        <PolicyBadge effect={session.policy_effect} />
        <SignatureBadge status={session.signature_status} />
        <IntegrityBadge status={session.fsck_status} />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {session.agent_name ? (
          <span>
            Agent <span className="text-foreground">{session.agent_name}</span>
          </span>
        ) : null}
        {session.model_name ? (
          <span>
            Model <span className="font-mono text-foreground">{session.model_name}</span>
          </span>
        ) : null}
        <span className="flex items-center gap-1">
          Base <Hash value={session.base_snapshot} len={10} />
        </span>
        {session.accepted_snapshot ? (
          <span className="flex items-center gap-1">
            Accepted <Hash value={session.accepted_snapshot} len={10} />
          </span>
        ) : null}
        <span>Started {formatTime(session.started_at)}</span>
        <span className="flex items-center gap-1">
          ID <Hash value={session.session_id} len={12} />
        </span>
      </div>
    </div>
  )
}
