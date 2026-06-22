"use client"

import { Camera, History, Save } from "lucide-react"
import { useState } from "react"

import { api } from "@/lib/checkpoint/api-client"
import { useApi } from "@/lib/checkpoint/use-api"
import { formatTime } from "@/lib/checkpoint/format"
import type { TimelineEvent } from "@/lib/checkpoint/types"
import { AppShell } from "@/components/checkpoint/app-shell"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ErrorState, LoadingState } from "@/components/checkpoint/states"
import { Hash } from "@/components/checkpoint/hash"
import { SessionHeader } from "@/components/checkpoint/session-header"
import { Timeline } from "@/components/checkpoint/timeline"
import { PacketSummary } from "@/components/checkpoint/packet-summary"
import { DiffViewer } from "@/components/checkpoint/diff-viewer"
import {
  ActionsPanel,
  IntegrityPanel,
  PolicyPanel,
  SignaturePanel,
  VerificationPanel,
} from "@/components/checkpoint/session-panels"

export function SessionReview({
  owner,
  repo,
  sessionId,
}: {
  owner: string
  repo: string
  sessionId: string
}) {
  const [selectedEvent, setSelectedEvent] = useState<string | undefined>()

  const session = useApi(() => api.getSession(owner, repo, sessionId), [owner, repo, sessionId])
  const timeline = useApi(() => api.getTimeline(owner, repo, sessionId), [owner, repo, sessionId])
  const diff = useApi(() => api.getDiff(owner, repo, sessionId), [owner, repo, sessionId])
  const packet = useApi(() => api.getPacket(owner, repo, sessionId), [owner, repo, sessionId])
  const verification = useApi(() => api.getVerification(owner, repo, sessionId), [owner, repo, sessionId])
  const policy = useApi(() => api.getPolicyDecision(owner, repo, sessionId), [owner, repo, sessionId])
  const signatures = useApi(() => api.getSignatures(owner, repo, sessionId), [owner, repo, sessionId])
  const integrity = useApi(() => api.getSessionIntegrity(owner, repo, sessionId), [owner, repo, sessionId])

  const crumbs = [
    { label: "Repos", href: "/repos" },
    { label: `${owner}/${repo}`, href: `/repos/${owner}/${repo}` },
    { label: "Session" },
  ]

  // Backend is "live" only when at least the session call hit a real API.
  const live = !session.isMock && !session.error

  const snapshots = (timeline.data ?? []).filter(
    (e) => e.type === "snapshot_created" || e.type === "autosave_created",
  )

  return (
    <AppShell crumbs={crumbs}>
      {session.loading ? (
        <LoadingState label="Loading session…" />
      ) : session.error ? (
        <ErrorState title="Could not load session" message={session.error} />
      ) : session.data ? (
        <div className="flex flex-col gap-5">
          <SessionHeader session={session.data} isMock={session.isMock} />

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
            {/* Left column — Timeline */}
            <aside className="lg:col-span-3">
              <Card className="gap-0 py-0">
                <CardHeader className="border-b border-border px-4 py-3">
                  <CardTitle className="flex items-center gap-2 text-sm">
                    <History className="size-4 text-muted-foreground" />
                    Timeline
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-2 py-3">
                  {timeline.loading ? (
                    <LoadingState />
                  ) : (
                    <Timeline
                      events={timeline.data ?? []}
                      selectedId={selectedEvent}
                      onSelect={(e: TimelineEvent) => setSelectedEvent(e.id)}
                    />
                  )}
                </CardContent>
              </Card>
            </aside>

            {/* Main column */}
            <section className="flex flex-col gap-4 lg:col-span-6">
              <PacketSummary packet={packet.data ?? null} files={diff.data ?? []} />

              <div className="flex flex-col gap-2">
                <h2 className="px-1 text-sm font-semibold text-foreground">Diff viewer</h2>
                {diff.loading ? <LoadingState /> : <DiffViewer files={diff.data ?? []} />}
              </div>

              {/* Snapshots & autosaves */}
              <Card className="gap-0 py-0">
                <CardHeader className="border-b border-border px-4 py-3">
                  <CardTitle className="flex items-center gap-2 text-sm">
                    <Camera className="size-4 text-muted-foreground" />
                    Snapshots &amp; Autosaves
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2 px-4 py-3">
                  {snapshots.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No snapshots recorded.</p>
                  ) : (
                    snapshots.map((s) => {
                      const isAuto = s.type === "autosave_created"
                      return (
                        <div
                          key={s.id}
                          className="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-2"
                        >
                          <div className="flex min-w-0 items-center gap-2">
                            {isAuto ? (
                              <Save className="size-4 shrink-0 text-muted-foreground" />
                            ) : (
                              <Camera className="size-4 shrink-0 text-foreground" />
                            )}
                            <div className="flex min-w-0 flex-col">
                              <span className="text-sm text-foreground">
                                {isAuto ? "Autosave" : "Snapshot"}
                              </span>
                              <span className="text-xs text-muted-foreground">{formatTime(s.at)}</span>
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            {isAuto ? (
                              <span className="rounded border border-warning/25 bg-warning-muted px-1.5 py-px text-[10px] font-medium tracking-wide text-warning uppercase">
                                recovery-only
                              </span>
                            ) : null}
                            {s.object_id ? <Hash value={s.object_id} len={8} /> : null}
                          </div>
                        </div>
                      )
                    })
                  )}
                </CardContent>
              </Card>
            </section>

            {/* Right column — review panels */}
            <aside className="flex flex-col gap-4 lg:col-span-3">
              <PolicyPanel decision={policy.data ?? null} />
              <VerificationPanel results={verification.data ?? []} />
              <SignaturePanel signatures={signatures.data ?? []} />
              <IntegrityPanel integrity={integrity.data ?? null} />
              <ActionsPanel live={live} />
            </aside>
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}
