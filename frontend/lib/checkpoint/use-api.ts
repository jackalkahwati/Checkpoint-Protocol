"use client"

import { useCallback, useEffect, useState } from "react"

import { ApiError, type ApiResult } from "./api-client"

interface State<T> {
  data: T | null
  isMock: boolean
  loading: boolean
  error: string | null
}

/**
 * Client-side fetch hook for the Checkpoint API.
 * `fetcher` should be one of the `api.*` methods returning ApiResult<T>.
 */
export function useApi<T>(
  fetcher: () => Promise<ApiResult<T>>,
  deps: unknown[] = [],
): State<T> & { reload: () => void } {
  const [state, setState] = useState<State<T>>({
    data: null,
    isMock: false,
    loading: true,
    error: null,
  })

  const run = useCallback(() => {
    let active = true
    setState((s) => ({ ...s, loading: true, error: null }))
    fetcher()
      .then((res) => {
        if (!active) return
        setState({ data: res.data, isMock: res.isMock, loading: false, error: null })
      })
      .catch((err: unknown) => {
        if (!active) return
        const message = err instanceof ApiError ? err.message : "Failed to load data."
        setState({ data: null, isMock: false, loading: false, error: message })
      })
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    const cleanup = run()
    return cleanup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { ...state, reload: run }
}
