"use client"

import { Check, Copy } from "lucide-react"
import { useState } from "react"

import { cn } from "@/lib/utils"
import { shortHash } from "@/lib/checkpoint/format"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

export function Hash({
  value,
  len = 10,
  className,
}: {
  value: string
  len?: number
  className?: string
}) {
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard?.writeText(value).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            onClick={copy}
            className={cn(
              "inline-flex items-center gap-1 rounded-sm font-mono text-xs text-muted-foreground transition-colors hover:text-foreground",
              className,
            )}
          />
        }
      >
        <span>{shortHash(value, len)}</span>
        {copied ? (
          <Check className="size-3 text-success" />
        ) : (
          <Copy className="size-3 opacity-50" />
        )}
      </TooltipTrigger>
      <TooltipContent>
        <span className="font-mono">{value}</span>
      </TooltipContent>
    </Tooltip>
  )
}
