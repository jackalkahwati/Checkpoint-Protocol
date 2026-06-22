import { AppShell } from "@/components/checkpoint/app-shell"
import { IdentitiesTab } from "@/components/checkpoint/repo-tabs"

export default async function IdentitiesPage({
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
        { label: "Identities" },
      ]}
    >
      <div className="flex flex-col gap-6">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Identities</h1>
        <IdentitiesTab owner={owner} repo={repo} />
      </div>
    </AppShell>
  )
}
