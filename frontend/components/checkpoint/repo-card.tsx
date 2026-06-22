"use client"

import { GitBranch, Layers } from "lucide-react"
import Link from "next/link"

import type { Repo } from "@/lib/checkpoint/types"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Hash } from "@/components/checkpoint/hash"
import {
  IntegrityBadge,
  PolicyBadge,
  SignatureBadge,
  TrustBadge,
} from "@/components/checkpoint/badges"

export function RepoCard({ repo }: { repo: Repo }) {
  return (
    <Link href={`/repos/${repo.owner}/${repo.name}`} className="group block">
      <Card className="h-full gap-0 py-0 transition-colors group-hover:border-primary/40">
        <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-border px-4 py-3">
          <span className="flex min-w-0 items-center gap-1.5 font-mono text-sm">
            <span className="text-muted-foreground">{repo.owner}/</span>
            <span className="truncate font-medium text-foreground">{repo.name}</span>
          </span>
          <IntegrityBadge status={repo.fsck_status} />
        </CardHeader>
        <CardContent className="flex flex-col gap-3 px-4 py-3">
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <GitBranch className="size-3.5" />
              {repo.branch_count} branches
            </span>
            <span className="flex items-center gap-1">
              <Layers className="size-3.5" />
              {repo.recent_sessions} sessions
            </span>
          </div>

          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            Latest accepted <Hash value={repo.latest_accepted_snapshot} len={12} />
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <PolicyBadge effect={repo.policy_status} />
            <SignatureBadge status={repo.signature_status} trust={repo.trust_status} />
            <TrustBadge trust={repo.trust_status} />
          </div>

          {repo.alerts.length > 0 ? (
            <div className="flex flex-col gap-1 border-t border-border pt-2">
              {repo.alerts.map((a, i) => (
                <p key={i} className="text-xs text-warning">
                  {a.message}
                </p>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </Link>
  )
}
