"use client"

import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Camera,
  CheckCircle2,
  GitMerge,
  PlayCircle,
  RotateCcw,
  Save,
  ShieldCheck,
  Signature as SignatureIcon,
  TestTube2,
  XCircle,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatTime } from "@/lib/checkpoint/format"
import type { TimelineEvent, TimelineEventType } from "@/lib/checkpoint/types"
import { Hash } from "@/components/checkpoint/hash"

const eventMeta: Record<TimelineEventType, { icon: LucideIcon; tone: string }> = {
  session_started: { icon: PlayCircle, tone: "text-info bg-info-muted" },
  autosave_created: { icon: Save, tone: "text-muted-foreground bg-muted" },
  snapshot_created: { icon: Camera, tone: "text-foreground bg-secondary" },
  verification_run: { icon: TestTube2, tone: "text-warning bg-warning-muted" },
  policy_check: { icon: ShieldCheck, tone: "text-info bg-info-muted" },
  signature_created: { icon: SignatureIcon, tone: "text-success bg-success-muted" },
  accepted: { icon: CheckCircle2, tone: "text-success bg-success-muted" },
  rejected: { icon: XCircle, tone: "text-danger bg-danger-muted" },
  rolled_back: { icon: RotateCcw, tone: "text-warning bg-warning-muted" },
  merged: { icon: GitMerge, tone: "text-info bg-info-muted" },
  pushed: { icon: ArrowUpFromLine, tone: "text-foreground bg-secondary" },
  fetched: { icon: ArrowDownToLine, tone: "text-foreground bg-secondary" },
}

export function Timeline({
  events,
  selectedId,
  onSelect,
}: {
  events: TimelineEvent[]
  selectedId?: string
  onSelect?: (e: TimelineEvent) => void
}) {
  return (
    <ol className="relative flex flex-col">
      {events.map((ev, i) => {
        const meta = eventMeta[ev.type]
        const Icon = meta.icon
        const isLast = i === events.length - 1
        const selected = selectedId === ev.id
        return (
          <li key={ev.id} className="relative">
            {!isLast && (
              <span className="absolute top-7 left-[15px] h-[calc(100%-1rem)] w-px bg-border" aria-hidden />
            )}
            <div
              className={cn(
                "group flex w-full items-start gap-3 rounded-md p-1.5 transition-colors hover:bg-muted/50",
                selected && "bg-muted/60",
              )}
            >
              <button
                type="button"
                onClick={() => onSelect?.(ev)}
                aria-pressed={selected}
                className="flex size-8 shrink-0 items-center justify-center rounded-full"
              >
                <span className={cn("flex size-8 items-center justify-center rounded-full", meta.tone)}>
                  <Icon className="size-4" />
                </span>
              </button>
              <div className="min-w-0 flex-1 pt-0.5">
                <button
                  type="button"
                  onClick={() => onSelect?.(ev)}
                  className="flex w-full items-center justify-between gap-2 text-left"
                >
                  <span className="truncate text-sm font-medium text-foreground">{ev.title}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatTime(ev.at)}</span>
                </button>
                {ev.detail ? (
                  <span className="mt-0.5 block text-xs text-muted-foreground">{ev.detail}</span>
                ) : null}
                <span className="mt-1 flex flex-wrap items-center gap-2">
                  {ev.recovery_only ? (
                    <span className="inline-flex items-center gap-1 rounded border border-warning/25 bg-warning-muted px-1.5 py-px text-[10px] font-medium tracking-wide text-warning uppercase">
                      recovery-only, not accepted history
                    </span>
                  ) : null}
                  {ev.object_id ? <Hash value={ev.object_id} len={8} /> : null}
                </span>
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
