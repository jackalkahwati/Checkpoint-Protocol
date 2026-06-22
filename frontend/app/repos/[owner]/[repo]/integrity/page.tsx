import { AppShell } from "@/components/checkpoint/app-shell"
import { IntegrityTab } from "@/components/checkpoint/repo-tabs"

export default async function IntegrityPage({
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
        { label: "Integrity" },
      ]}
    >
      <div className="flex flex-col gap-6">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Integrity</h1>
        <IntegrityTab owner={owner} repo={repo} />
      </div>
    </AppShell>
  )
}
