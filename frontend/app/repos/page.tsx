"use client"

import { useEffect, useState } from "react"
import { AlertTriangle, LayoutGrid, List } from "lucide-react"

import { api } from "@/lib/checkpoint/api-client"
import { useApi } from "@/lib/checkpoint/use-api"
import type { RepoAlert } from "@/lib/checkpoint/types"
import { cn } from "@/lib/utils"
import { AppShell } from "@/components/checkpoint/app-shell"
import { MockBadge } from "@/components/checkpoint/badges"
import { RepoCard } from "@/components/checkpoint/repo-card"
import { RepoList } from "@/components/checkpoint/repo-list"
import { ErrorState, LoadingState } from "@/components/checkpoint/states"

type View = "grid" | "list"
const VIEW_KEY = "checkpoint_repos_view"

export default function ReposPage() {
  const { data, loading, error, isMock } = useApi(() => api.listRepos(), [])
  const [view, setView] = useState<View>("grid")

  useEffect(() => {
    const saved = localStorage.getItem(VIEW_KEY)
    if (saved === "grid" || saved === "list") setView(saved)
  }, [])

  function choose(v: View) {
    setView(v)
    localStorage.setItem(VIEW_KEY, v)
  }

  const alerts: { repo: string; alert: RepoAlert }[] = (data ?? []).flatMap((r) =>
    r.alerts.map((alert) => ({ repo: `${r.owner}/${r.name}`, alert })),
  )

  return (
    <AppShell crumbs={[{ label: "Repos" }]}>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">Repositories</h1>
            <p className="text-sm text-muted-foreground">
              Hosted Checkpoint repos. Checkpoint reviews work sessions, not just commits.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {isMock ? <MockBadge /> : null}
            <div className="flex items-center rounded-md border border-border p-0.5" role="group" aria-label="View">
              <button
                type="button"
                onClick={() => choose("grid")}
                aria-pressed={view === "grid"}
                title="Grid view"
                className={cn(
                  "flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors",
                  view === "grid" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <LayoutGrid className="size-3.5" /> Grid
              </button>
              <button
                type="button"
                onClick={() => choose("list")}
                aria-pressed={view === "list"}
                title="List view"
                className={cn(
                  "flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors",
                  view === "list" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <List className="size-3.5" /> List
              </button>
            </div>
          </div>
        </div>

        {alerts.length > 0 ? (
          <div className="flex flex-col gap-1.5 rounded-lg border border-warning/25 bg-warning-muted/30 p-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-warning uppercase">
              <AlertTriangle className="size-3.5" />
              Attention required
            </p>
            <ul className="flex flex-col gap-1">
              {alerts.map((a, i) => (
                <li key={i} className="text-sm text-foreground">
                  <span className="font-mono text-muted-foreground">{a.repo}</span> — {a.alert.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {loading ? (
          <LoadingState label="Loading repositories…" />
        ) : error ? (
          <ErrorState title="Could not load repositories" message={error} />
        ) : view === "list" ? (
          <RepoList repos={data ?? []} />
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {(data ?? []).map((repo) => (
              <RepoCard key={`${repo.owner}/${repo.name}`} repo={repo} />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  )
}
