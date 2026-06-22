import { AppShell } from "@/components/checkpoint/app-shell"
import { PolicyTab } from "@/components/checkpoint/repo-tabs"

export default async function PolicyPage({
  params,
}: {
  params: Promise<{ owner: string; repo: string }>
}) {
  const { owner, repo } = await params
  const slug = `${owner}/${repo}`
  return (
    <AppShell
      crumbs={[
        { label: "Repos", href: "/repos" },
        { label: slug, href: `/repos/${slug}` },
        { label: "Policy" },
      ]}
    >
      <div className="flex flex-col gap-6">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Policy</h1>
        <PolicyTab owner={owner} repo={repo} />
      </div>
    </AppShell>
  )
}
