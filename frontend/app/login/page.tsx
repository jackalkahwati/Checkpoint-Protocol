"use client"

import { AlertTriangle, KeyRound } from "lucide-react"
import { useRouter } from "next/navigation"
import { useState } from "react"

import { DEFAULT_BASE_URL, setSession } from "@/lib/checkpoint/api-client"
import { CheckpointLogo } from "@/components/checkpoint/app-shell"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"

export default function LoginPage() {
  const router = useRouter()
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL)
  const [token, setToken] = useState("")

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    // Local MVP: any token is accepted and stored. The API client falls
    // back to mock data when the backend is unreachable.
    setSession(token || "mock-token", baseUrl)
    router.push("/repos")
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="text-lg font-semibold tracking-tight text-foreground">
            <CheckpointLogo />
          </span>
          <p className="text-pretty text-sm text-muted-foreground">
            Review the work session, not just the commit.
          </p>
        </div>

        <Card>
          <CardContent>
            <form onSubmit={onSubmit}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="baseUrl">API base URL</FieldLabel>
                  <Input
                    id="baseUrl"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder={DEFAULT_BASE_URL}
                    autoComplete="off"
                    spellCheck={false}
                    className="font-mono"
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="token">API token</FieldLabel>
                  <Input
                    id="token"
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="checkpoint_pat_…"
                    autoComplete="off"
                  />
                  <FieldDescription>Sent as a Bearer token on every request.</FieldDescription>
                </Field>
                <Button type="submit" className="w-full">
                  <KeyRound data-icon="inline-start" />
                  Log in
                </Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>

        <div className="flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted/40 p-3 text-xs text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>Local MVP token storage. Do not use production credentials.</span>
        </div>
      </div>
    </div>
  )
}
