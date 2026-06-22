"use client"

import { Lightbulb, Package } from "lucide-react"

import type { DiffFile, SessionPacket } from "@/lib/checkpoint/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Hash } from "@/components/checkpoint/hash"

export function PacketSummary({
  packet,
  files,
}: {
  packet: SessionPacket | null
  files: DiffFile[]
}) {
  const additions = files.reduce((a, f) => a + f.additions, 0)
  const deletions = files.reduce((a, f) => a + f.deletions, 0)

  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-border px-4 py-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Package className="size-4 text-muted-foreground" />
          Packet Summary
        </CardTitle>
        <span className="font-mono text-xs">
          <span className="text-muted-foreground">{files.length} files</span>{" "}
          {additions > 0 ? <span className="text-success">+{additions}</span> : null}{" "}
          {deletions > 0 ? <span className="text-danger">-{deletions}</span> : null}
        </span>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-4 py-3">
        {!packet ? (
          <p className="text-sm text-muted-foreground">No packet summary available for this session.</p>
        ) : (
          <>
            <p className="text-sm leading-relaxed text-foreground">{packet.summary}</p>

            {packet.risk_tags.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Risk</span>
                {packet.risk_tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded border border-danger/25 bg-danger-muted px-1.5 py-px text-[11px] font-medium text-danger"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}

            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Changed paths</span>
              <ul className="flex flex-col gap-0.5">
                {packet.changed_paths.map((p) => (
                  <li key={p} className="truncate font-mono text-xs text-foreground">
                    {p}
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex items-start gap-2 rounded-md border border-info/25 bg-info-muted/40 p-2.5">
              <Lightbulb className="mt-0.5 size-4 shrink-0 text-info" />
              <div className="flex flex-col gap-0.5">
                <span className="text-xs font-semibold tracking-wide text-info uppercase">Recommended action</span>
                <span className="text-sm text-foreground">{packet.recommended_action}</span>
              </div>
            </div>

            {packet.accepted_snapshot ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                Accepted snapshot <Hash value={packet.accepted_snapshot} len={12} />
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  )
}
