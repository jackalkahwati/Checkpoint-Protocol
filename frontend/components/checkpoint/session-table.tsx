"use client"

import { GitBranch } from "lucide-react"
import { useRouter } from "next/navigation"

import { formatTime } from "@/lib/checkpoint/format"
import type { Session } from "@/lib/checkpoint/types"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  ActorBadge,
  PolicyBadge,
  SignatureBadge,
  StatusBadge,
  VerificationBadge,
} from "@/components/checkpoint/badges"

export function SessionTable({
  sessions,
  owner,
  repo,
}: {
  sessions: Session[]
  owner: string
  repo: string
}) {
  const router = useRouter()

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow className="bg-secondary/40 hover:bg-secondary/40">
            <TableHead>Instruction</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Branch</TableHead>
            <TableHead>Review</TableHead>
            <TableHead className="text-right">Started</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sessions.map((s) => (
            <TableRow
              key={s.session_id}
              onClick={() => router.push(`/repos/${owner}/${repo}/sessions/${s.session_id}`)}
              className="cursor-pointer"
            >
              <TableCell className="max-w-xs">
                <div className="flex flex-col gap-1">
                  <span className="truncate font-medium text-foreground">{s.instruction}</span>
                  {s.risk_tags.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {s.risk_tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded border border-danger/25 bg-danger-muted px-1 py-px text-[10px] font-medium text-danger"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <StatusBadge status={s.status} />
              </TableCell>
              <TableCell>
                <ActorBadge name={s.actor_identity} type={s.actor_type} />
              </TableCell>
              <TableCell>
                <span className="flex items-center gap-1 font-mono text-xs text-muted-foreground">
                  <GitBranch className="size-3" />
                  {s.branch}
                </span>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1">
                  <VerificationBadge status={s.verification_status} />
                  <PolicyBadge effect={s.policy_effect} />
                  <SignatureBadge status={s.signature_status} />
                </div>
              </TableCell>
              <TableCell className="text-right text-xs text-muted-foreground whitespace-nowrap">
                {formatTime(s.started_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
