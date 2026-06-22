import { AppShell } from "@/components/checkpoint/app-shell"
import { ReviewDetail } from "@/components/checkpoint/reviews"

export default async function ReviewPage({
  params,
}: {
  params: Promise<{ owner: string; repo: string; id: string }>
}) {
  const { owner, repo, id } = await params
  const slug = `${owner}/${repo}`
  return (
    <AppShell
      crumbs={[
        { label: "Repos", href: "/repos" },
        { label: slug, href: `/repos/${slug}` },
        { label: "Merge requests", href: `/repos/${slug}` },
        { label: id },
      ]}
    >
      <ReviewDetail owner={owner} repo={repo} id={id} />
    </AppShell>
  )
}
