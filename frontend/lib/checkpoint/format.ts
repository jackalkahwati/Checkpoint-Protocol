export function shortHash(hash: string, len = 10): string {
  if (!hash) return ""
  const cleaned = hash.replace(/^(snap_|auto_|sig_|ver_|pol_|rcpt_|sess_)/, "")
  const prefix = hash.match(/^(snap_|auto_|sig_|ver_|pol_|rcpt_|sess_)/)?.[0] ?? ""
  if (cleaned.length <= len) return hash
  return `${prefix}${cleaned.slice(0, len)}`
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return iso
  const diff = Date.now() - then
  const min = Math.round(diff / 60000)
  if (min < 1) return "just now"
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.round(hr / 24)
  if (day < 30) return `${day}d ago`
  return new Date(iso).toLocaleDateString()
}

export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function formatDuration(ms: number): string {
  if (ms === 0) return "—"
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
