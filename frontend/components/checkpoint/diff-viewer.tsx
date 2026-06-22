"use client"

import {
  ChevronDown,
  ChevronRight,
  FileDiff,
  FileMinus,
  FilePlus,
  FileWarning,
  FileX,
  ImageIcon,
  MessageSquarePlus,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useState } from "react"

import { cn } from "@/lib/utils"
import type { ChangeType, DiffFile, DiffLine, MRComment } from "@/lib/checkpoint/types"

// Optional review hooks: when provided, the diff supports inline line comments.
export interface DiffReview {
  comments: MRComment[]
  onAddComment: (path: string, line: number | null, body: string) => Promise<void> | void
  onResolve?: (commentId: string, resolved: boolean) => Promise<void> | void
}

const changeMeta: Record<ChangeType, { icon: LucideIcon; label: string; tone: string }> = {
  added: { icon: FilePlus, label: "added", tone: "text-success" },
  deleted: { icon: FileMinus, label: "deleted", tone: "text-danger" },
  modified: { icon: FileDiff, label: "modified", tone: "text-info" },
  renamed: { icon: FileDiff, label: "renamed", tone: "text-warning" },
  binary: { icon: ImageIcon, label: "binary", tone: "text-muted-foreground" },
  conflict: { icon: FileWarning, label: "conflict", tone: "text-danger" },
}

function FilePath({ file }: { file: DiffFile }) {
  if (file.change_type === "renamed") {
    return (
      <span className="flex min-w-0 flex-wrap items-center gap-1.5 font-mono text-xs">
        <span className="truncate text-muted-foreground line-through decoration-danger/50">{file.old_path}</span>
        <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
        <span className="truncate text-foreground">{file.new_path}</span>
      </span>
    )
  }
  const path = file.change_type === "added" ? file.new_path : file.change_type === "deleted" ? file.old_path : file.new_path
  return <span className="truncate font-mono text-xs text-foreground">{path}</span>
}

function lineClass(kind: DiffLine["kind"]): string {
  switch (kind) {
    case "add":
      return "bg-success-muted text-foreground"
    case "del":
      return "bg-danger-muted text-foreground"
    case "conflict-ours":
      return "bg-info-muted text-foreground"
    case "conflict-theirs":
      return "bg-warning-muted text-foreground"
    case "conflict-marker":
      return "bg-danger/15 font-semibold text-danger"
    default:
      return "text-muted-foreground"
  }
}

function lineMarker(kind: DiffLine["kind"]): string {
  if (kind === "add" || kind === "conflict-ours" || kind === "conflict-theirs") return "+"
  if (kind === "del") return "-"
  if (kind === "conflict-marker") return "!"
  return " "
}

function hunkNewStart(header: string): number {
  const m = header.match(/\+(\d+)/)
  return m ? parseInt(m[1], 10) : 1
}

function LineComment({ c, review }: { c: MRComment; review?: DiffReview }) {
  return (
    <div className="mx-3 my-1 rounded-md border border-border bg-card px-2.5 py-1.5 font-sans text-xs whitespace-normal">
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground">
          <span className="font-medium text-foreground">{c.author}</span>
          {c.resolved ? <span className="ml-1 text-success">· resolved</span> : null}
        </span>
        {review?.onResolve ? (
          <button
            type="button"
            className="text-[11px] text-muted-foreground hover:text-foreground"
            onClick={() => review.onResolve?.(c.id, !c.resolved)}
          >
            {c.resolved ? "Reopen" : "Resolve"}
          </button>
        ) : null}
      </div>
      <p className="mt-0.5 text-foreground">{c.body}</p>
    </div>
  )
}

function InlineComposer({
  onSubmit,
  onCancel,
}: {
  onSubmit: (body: string) => void
  onCancel: () => void
}) {
  const [body, setBody] = useState("")
  return (
    <div className="mx-3 my-1 flex flex-col gap-1.5 rounded-md border border-border bg-card p-2 font-sans">
      <textarea
        autoFocus
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={2}
        placeholder="Comment on this line…"
        className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
      />
      <div className="flex justify-end gap-1.5">
        <button type="button" className="rounded px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="rounded bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
          disabled={!body.trim()}
          onClick={() => body.trim() && onSubmit(body.trim())}
        >
          Comment
        </button>
      </div>
    </div>
  )
}

function DiffBody({ file, review }: { file: DiffFile; review?: DiffReview }) {
  const [composeAt, setComposeAt] = useState<number | null>(null)
  if (file.change_type === "binary") {
    return (
      <div className="flex items-center gap-2 px-3 py-4 text-xs text-muted-foreground">
        <ImageIcon className="size-4" />
        Binary file changed — no textual diff available.
      </div>
    )
  }
  const byLine = new Map<number, MRComment[]>()
  if (review) {
    for (const c of review.comments) {
      if (c.path === file.new_path && typeof c.line === "number") {
        byLine.set(c.line, [...(byLine.get(c.line) ?? []), c])
      }
    }
  }
  return (
    <div className="overflow-x-auto">
      {file.hunks.map((hunk, hi) => {
        let newLine = hunkNewStart(hunk.header) - 1
        return (
          <div key={hi}>
            <div className="bg-secondary/60 px-3 py-1 font-mono text-[11px] text-muted-foreground">{hunk.header}</div>
            <div className="font-mono text-xs leading-relaxed">
              {hunk.lines.map((line, li) => {
                const hasNew = line.kind !== "del" && line.kind !== "conflict-marker"
                if (hasNew) newLine += 1
                const ln = hasNew ? newLine : null
                const lineComments = ln !== null ? byLine.get(ln) ?? [] : []
                return (
                  <div key={li}>
                    <div className={cn("group flex items-start", lineClass(line.kind))}>
                      {review && ln !== null ? (
                        <button
                          type="button"
                          title="Comment on this line"
                          onClick={() => setComposeAt(composeAt === ln ? null : ln)}
                          className="mt-px hidden w-5 shrink-0 text-center text-primary group-hover:block hover:text-primary/80"
                        >
                          +
                        </button>
                      ) : review ? (
                        <span className="w-5 shrink-0" />
                      ) : null}
                      <span className="w-10 shrink-0 select-none pr-2 text-right text-[10px] text-muted-foreground/60">
                        {ln ?? ""}
                      </span>
                      <span className="flex-1 whitespace-pre px-1">
                        <span className="mr-1 inline-block w-2 text-center opacity-70">{lineMarker(line.kind)}</span>
                        {line.text || " "}
                      </span>
                    </div>
                    {lineComments.map((c) => (
                      <LineComment key={c.id} c={c} review={review} />
                    ))}
                    {review && composeAt === ln && ln !== null ? (
                      <InlineComposer
                        onCancel={() => setComposeAt(null)}
                        onSubmit={async (b) => {
                          await review.onAddComment(file.new_path, ln, b)
                          setComposeAt(null)
                        }}
                      />
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function DiffFileCard({ file, defaultOpen, review }: { file: DiffFile; defaultOpen?: boolean; review?: DiffReview }) {
  const [open, setOpen] = useState(defaultOpen ?? file.change_type === "conflict")
  const meta = changeMeta[file.change_type]
  const Icon = meta.icon
  const fileComments = review ? review.comments.filter((c) => c.path === file.new_path && (c.line === null || c.line === undefined)) : []

  return (
    <div id={`file-${file.new_path}`} className="overflow-hidden rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/40"
      >
        {open ? (
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        )}
        <Icon className={cn("size-4 shrink-0", meta.tone)} />
        <span className="min-w-0 flex-1">
          <FilePath file={file} />
        </span>
        {file.change_type === "renamed" && file.similarity !== undefined ? (
          <span className="shrink-0 rounded border border-warning/25 bg-warning-muted px-1.5 text-[11px] font-medium text-warning">
            similarity {file.similarity}%
          </span>
        ) : null}
        <span className="shrink-0 font-mono text-xs">
          {file.additions > 0 ? <span className="text-success">+{file.additions}</span> : null}{" "}
          {file.deletions > 0 ? <span className="text-danger">-{file.deletions}</span> : null}
        </span>
      </button>
      {open ? (
        <div className="border-t border-border">
          {file.change_type === "conflict" ? (
            <div className="flex items-center gap-3 border-b border-border bg-danger-muted/40 px-3 py-1.5 text-[11px] font-medium">
              <span className="text-info">■ ours</span>
              <span className="text-warning">■ theirs</span>
              <span className="text-muted-foreground">Resolve before acceptance</span>
            </div>
          ) : null}
          {fileComments.length > 0 ? (
            <div className="border-b border-border py-1">
              {fileComments.map((c) => (
                <LineComment key={c.id} c={c} review={review} />
              ))}
            </div>
          ) : null}
          <DiffBody file={file} review={review} />
        </div>
      ) : null}
    </div>
  )
}

export function DiffViewer({ files, review }: { files: DiffFile[]; review?: DiffReview }) {
  if (files.length === 0) {
    return <p className="px-1 py-6 text-center text-sm text-muted-foreground">No file changes in this session.</p>
  }
  return (
    <div className="flex flex-col gap-2">
      {/* File list / jump links */}
      <div className="flex flex-wrap gap-1.5 rounded-lg border border-border bg-card/50 p-2">
        {files.map((f) => {
          const meta = changeMeta[f.change_type]
          const Icon = meta.icon
          const name = (f.change_type === "deleted" ? f.old_path : f.new_path).split("/").pop()
          return (
            <a
              key={f.new_path + f.old_path}
              href={`#file-${f.new_path}`}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:text-foreground"
            >
              <Icon className={cn("size-3", meta.tone)} />
              {name}
            </a>
          )
        })}
      </div>
      {files.map((f) => (
        <DiffFileCard key={f.new_path + f.old_path} file={f} review={review} />
      ))}
    </div>
  )
}

export { FileX }
