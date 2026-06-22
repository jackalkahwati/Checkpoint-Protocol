"use client"

import { ChevronRight, GitFork, LogOut } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState, type ReactNode } from "react"

import { api, clearSession, isAuthenticated } from "@/lib/checkpoint/api-client"
import { useApi } from "@/lib/checkpoint/use-api"
import { Button } from "@/components/ui/button"
import { Pill } from "@/components/checkpoint/badges"

export interface Crumb {
  label: string
  href?: string
}

export function CheckpointLogo({ className }: { className?: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <GitFork className="size-4" />
      </span>
      <span className={className}>Checkpoint</span>
    </span>
  )
}

function HealthBadge() {
  const { data, loading, isMock } = useApi(() => api.getHealth(), [])
  if (loading) {
    return (
      <Pill tone="neutral">API …</Pill>
    )
  }
  if (isMock || !data?.ok) {
    return (
      <Pill tone="warning" tip="Could not reach the Checkpoint API (mock mode)">
        API offline
      </Pill>
    )
  }
  return (
    <Pill tone="success" tip={`Checkpoint API v${data.version}`}>
      API online
    </Pill>
  )
}

export function AppShell({
  crumbs = [],
  children,
}: {
  crumbs?: Crumb[]
  children: ReactNode
}) {
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login")
    } else {
      setReady(true)
    }
  }, [router])

  function logout() {
    clearSession()
    router.replace("/login")
  }

  if (!ready) return null

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-[1600px] items-center gap-4 px-4 md:px-6">
          <Link href="/repos" className="text-sm font-semibold tracking-tight text-foreground">
            <CheckpointLogo />
          </Link>
          <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-sm md:flex">
            {crumbs.map((c, i) => (
              <span key={`${c.label}-${i}`} className="flex min-w-0 items-center gap-1.5">
                <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" />
                {c.href ? (
                  <Link
                    href={c.href}
                    className="truncate text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {c.label}
                  </Link>
                ) : (
                  <span className="truncate font-medium text-foreground">{c.label}</span>
                )}
              </span>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <HealthBadge />
            <Button variant="ghost" size="sm" onClick={logout}>
              <LogOut data-icon="inline-start" />
              Logout
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 md:px-6">{children}</main>
    </div>
  )
}
