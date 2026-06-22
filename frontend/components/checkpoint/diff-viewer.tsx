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
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useState } from "react"

import { cn } from "@/lib/utils"
import type { ChangeType, DiffFile, DiffLine } from "@/lib/checkpoint/types"

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
      return "bg-success-muted text-foreground before:content-['+'] before:text-success"
    case "del":
      return "bg-danger-muted text-foreground before:content-['-'] before:text-danger"
    case "conflict-ours":
      return "bg-info-muted text-foreground before:content-['+']"
    case "conflict-theirs":
      return "bg-warning-muted text-foreground before:content-['+']"
    case "conflict-marker":
      return "bg-danger/15 font-semibold text-danger before:content-['!']"
    default:
      return "text-muted-foreground before:content-['_'] before:opacity-0"
  }
}

function DiffBody({ file }: { file: DiffFile }) {
  if (file.change_type === "binary") {
    return (
      <div className="flex items-center gap-2 px-3 py-4 text-xs text-muted-foreground">
        <ImageIcon className="size-4" />
        Binary file changed — no textual diff available.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto">
      {file.hunks.map((hunk, hi) => (
        <div key={hi}>
          <div className="bg-secondary/60 px-3 py-1 font-mono text-[11px] text-muted-foreground">{hunk.header}</div>
          <pre className="font-mono text-xs leading-relaxed">
            {hunk.lines.map((line, li) => (
              <div
                key={li}
                className={cn(
                  "px-3 before:mr-2 before:inline-block before:w-2 before:text-center",
                  lineClass(line.kind),
                )}
              >
                {line.text || " "}
              </div>
            ))}
          </pre>
        </div>
      ))}
    </div>
  )
}

function DiffFileCard({ file, defaultOpen }: { file: DiffFile; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen ?? file.change_type === "conflict")
  const meta = changeMeta[file.change_type]
  const Icon = meta.icon

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
          <DiffBody file={file} />
        </div>
      ) : null}
    </div>
  )
}

export function DiffViewer({ files }: { files: DiffFile[] }) {
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
        <DiffFileCard key={f.new_path + f.old_path} file={f} />
      ))}
    </div>
  )
}

export { FileX }
