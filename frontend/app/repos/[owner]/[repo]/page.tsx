import { AppShell } from "@/components/checkpoint/app-shell"
import { RepoDetail } from "@/components/checkpoint/repo-detail"

export default async function RepoPage({
  params,
}: {
  params: Promise<{ owner: string; repo: string }>
}) {
  const { owner, repo } = await params
  return (
    <AppShell
      crumbs={[
        { label: "Repos", href: "/repos" },
        { label: `${owner}/${repo}` },
      ]}
    >
      <RepoDetail owner={owner} repo={repo} />
    </AppShell>
  )
}
