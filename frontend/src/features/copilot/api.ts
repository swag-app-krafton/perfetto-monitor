import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { postSse } from '@/lib/sse'
import type { ContextItem, CopilotEvent, CopilotPin, Feedback, ThreadDetail, ThreadSummary } from './types'

export interface AskRequest {
  text: string
  context: ContextItem[]
  scope: { app?: string; path?: string }
  deep: boolean
  thread_id: number | null
}

/** Stream one answer. Events arrive as the server produces them; aborting
 *  `signal` stops the stream (and the server stops working on it). */
export async function* ask(req: AskRequest, signal: AbortSignal): AsyncGenerator<CopilotEvent> {
  for await (const ev of postSse('/api/copilot/ask', req, signal)) yield ev as CopilotEvent
}

export const copilotKeys = {
  threads: ['copilot', 'threads'] as const,
  thread: (id: number) => ['copilot', 'thread', id] as const,
  pins: ['copilot', 'pins'] as const,
}

export const useThreads = (enabled: boolean) =>
  useQuery({
    queryKey: copilotKeys.threads,
    queryFn: () => api.get<{ threads: ThreadSummary[] }>('/api/copilot/threads').then((r) => r.threads),
    enabled,
    staleTime: 0,
  })

export const fetchThread = (id: number) => api.get<ThreadDetail>(`/api/copilot/threads?id=${id}`)

export const sendFeedback = (messageId: number, value: Feedback) => api.post('/api/copilot/feedback', { message_id: messageId, value })

/** Pins, all runs: few enough to fetch whole, and Overview filters by run. */
export const usePins = () =>
  useQuery({
    queryKey: copilotKeys.pins,
    queryFn: () => api.get<{ pins: CopilotPin[] }>('/api/copilot/pins').then((r) => r.pins),
  })

export function usePinMutations() {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: copilotKeys.pins })
  return {
    pin: useMutation({
      mutationFn: (messageId: number) => api.post<{ pin: CopilotPin }>('/api/copilot/pin', { message_id: messageId }).then((r) => r.pin),
      onSuccess: refresh,
    }),
    unpin: useMutation({ mutationFn: (id: number) => api.post('/api/copilot/unpin', { id }), onSuccess: refresh }),
  }
}
