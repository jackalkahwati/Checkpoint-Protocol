import { AlertTriangle, Inbox, Loader2 } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function LoadingState({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground", className)}>
      <Loader2 className="size-4 animate-spin" />
      {label}
    </div>
  )
}

export function ErrorState({
  title = "Something went wrong",
  message,
  className,
}: {
  title?: string
  message?: string
  className?: string
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 py-12 text-center", className)}>
      <div className="flex size-10 items-center justify-center rounded-full bg-danger-muted text-danger">
        <AlertTriangle className="size-5" />
      </div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      {message ? <p className="max-w-sm text-sm text-muted-foreground">{message}</p> : null}
    </div>
  )
}

export function EmptyState({
  title,
  message,
  icon,
  className,
  action,
}: {
  title: string
  message?: string
  icon?: ReactNode
  className?: string
  action?: ReactNode
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 py-12 text-center", className)}>
      <div className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
        {icon ?? <Inbox className="size-5" />}
      </div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      {message ? <p className="max-w-sm text-sm text-muted-foreground">{message}</p> : null}
      {action}
    </div>
  )
}
