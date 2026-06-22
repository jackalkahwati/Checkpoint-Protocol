"use client"

import Link from "next/link"
import { useState } from "react"

import { api } from "@/lib/checkpoint/api-client"
import { useApi } from "@/lib/checkpoint/use-api"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import type { Repo, Session } from "@/lib/checkpoint/types"
import { ErrorState, LoadingState } from "@/components/checkpoint/states"
import { SessionTable } from "@/components/checkpoint/session-table"
import {
  AuditTab,
  BranchesTab,
  IdentitiesTab,
  IntegrityTab,
  PolicyTab,
} from "@/components/checkpoint/repo-tabs"
import { ReviewsTab } from "@/components/checkpoint/reviews"
import {
  IntegrityBadge,
  MockBadge,
  PolicyBadge,
  SignatureBadge,
  TrustBadge,
} from "@/components/checkpoint/badges"
import { Hash } from "@/components/checkpoint/hash"

export function RepoDetail({ owner, repo }: { owner: string; repo: string }) {
  const [tab, setTab] = useState("sessions")
  const repoQuery = useApi<Repo>(() => api.getRepo(owner, repo), [owner, repo])
  const sessionsQuery = useApi<Session[]>(() => api.listSessions(owner, repo), [owner, repo])

  if (repoQuery.loading) return <LoadingState label="Loading repository…" />
  if (repoQuery.error || !repoQuery.data)
    return <ErrorState title="Could not load repository" message={repoQuery.error ?? undefined} />

  const data = repoQuery.data
  const head = sessionsQuery.data?.[0]

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-3">
            <h1 className="font-mono text-xl text-foreground">
              <span className="text-muted-foreground">{data.owner}/</span>
              {data.name}
            </h1>
            {repoQuery.isMock ? <MockBadge /> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{data.branch_count} branches</span>
            <span>·</span>
            <span>{data.recent_sessions} recent sessions</span>
            <span>·</span>
            <span>latest accepted</span>
            <Hash value={data.latest_accepted_snapshot} len={12} />
          </div>
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <PolicyBadge effect={data.policy_status} />
            <SignatureBadge status={data.signature_status} trust={data.trust_status} />
            <TrustBadge trust={data.trust_status} />
            <IntegrityBadge status={data.fsck_status} />
          </div>
        </div>
        {head ? (
          <Button
            variant="outline"
            size="sm"
            nativeButton={false}
            render={<Link href={`/repos/${owner}/${repo}/sessions/${head.session_id}`} />}
          >
            Latest session
          </Button>
        ) : null}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="sessions">Sessions</TabsTrigger>
          <TabsTrigger value="reviews">Merge requests</TabsTrigger>
          <TabsTrigger value="branches">Branches</TabsTrigger>
          <TabsTrigger value="policy">Policy</TabsTrigger>
          <TabsTrigger value="identities">Identities</TabsTrigger>
          <TabsTrigger value="integrity">Integrity</TabsTrigger>
          <TabsTrigger value="audit">Audit</TabsTrigger>
        </TabsList>
        <TabsContent value="sessions" className="mt-6">
          {sessionsQuery.loading ? (
            <LoadingState label="Loading sessions…" />
          ) : (
            <SessionTable sessions={sessionsQuery.data ?? []} owner={owner} repo={repo} />
          )}
        </TabsContent>
        <TabsContent value="reviews" className="mt-6">
          <ReviewsTab owner={owner} repo={repo} />
        </TabsContent>
        <TabsContent value="branches" className="mt-6">
          <BranchesTab owner={owner} repo={repo} />
        </TabsContent>
        <TabsContent value="policy" className="mt-6">
          <PolicyTab owner={owner} repo={repo} />
        </TabsContent>
        <TabsContent value="identities" className="mt-6">
          <IdentitiesTab owner={owner} repo={repo} />
        </TabsContent>
        <TabsContent value="integrity" className="mt-6">
          <IntegrityTab owner={owner} repo={repo} />
        </TabsContent>
        <TabsContent value="audit" className="mt-6">
          <AuditTab owner={owner} repo={repo} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
