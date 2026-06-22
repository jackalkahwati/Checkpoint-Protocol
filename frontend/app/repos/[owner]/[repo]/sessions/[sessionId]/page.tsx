import { SessionReview } from "@/components/checkpoint/session-review"

export default async function SessionPage({
  params,
}: {
  params: Promise<{ owner: string; repo: string; sessionId: string }>
}) {
  const { owner, repo, sessionId } = await params
  return <SessionReview owner={owner} repo={repo} sessionId={sessionId} />
}
