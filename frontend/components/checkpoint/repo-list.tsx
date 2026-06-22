"use client"

import { AlertTriangle, GitBranch, Layers } from "lucide-react"
import { useRouter } from "next/navigation"

import type { Repo } from "@/lib/checkpoint/types"
import { Hash } from "@/components/checkpoint/hash"
import {
  IntegrityBadge,
  PolicyBadge,
  SignatureBadge,
  TrustBadge,
} from "@/components/checkpoint/badges"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export function RepoList({ repos }: { repos: Repo[] }) {
  const router = useRouter()
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Repository</TableHead>
            <TableHead className="text-right">Branches</TableHead>
            <TableHead className="text-right">Sessions</TableHead>
            <TableHead>Latest accepted</TableHead>
            <TableHead>Review</TableHead>
            <TableHead>Integrity</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {repos.map((repo) => {
            const href = `/repos/${repo.owner}/${repo.name}`
            return (
              <TableRow
                key={`${repo.owner}/${repo.name}`}
                onClick={() => router.push(href)}
                className="cursor-pointer"
              >
                <TableCell>
                  <span className="flex min-w-0 items-center gap-1.5 font-mono text-sm">
                    <span className="text-muted-foreground">{repo.owner}/</span>
                    <span className="truncate font-medium text-foreground">{repo.name}</span>
                  </span>
                  {repo.alerts.length > 0 ? (
                    <span className="mt-0.5 flex items-center gap-1 text-xs text-warning">
                      <AlertTriangle className="size-3" />
                      {repo.alerts[0].message}
                      {repo.alerts.length > 1 ? ` (+${repo.alerts.length - 1})` : ""}
                    </span>
                  ) : null}
                </TableCell>
                <TableCell className="text-right text-sm text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <GitBranch className="size-3.5" />
                    {repo.branch_count}
                  </span>
                </TableCell>
                <TableCell className="text-right text-sm text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <Layers className="size-3.5" />
                    {repo.recent_sessions}
                  </span>
                </TableCell>
                <TableCell>
                  <Hash value={repo.latest_accepted_snapshot} len={12} />
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <PolicyBadge effect={repo.policy_status} />
                    <SignatureBadge status={repo.signature_status} trust={repo.trust_status} />
                    <TrustBadge trust={repo.trust_status} />
                  </div>
                </TableCell>
                <TableCell>
                  <IntegrityBadge status={repo.fsck_status} />
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
