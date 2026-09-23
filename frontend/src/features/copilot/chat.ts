import { create } from 'zustand'
import { ask, fetchThread, sendFeedback, type AskRequest } from './api'
import type { AnswerBlock, ChatMessage, ContextItem, Feedback, StoredMessage } from './types'

/** The conversation, held outside the panel so it survives closing the
 *  panel and changing tabs. One request streams at a time. */
interface ChatState {
  messages: ChatMessage[]
  threadId: number | null
  busy: boolean
  deep: boolean
  view: 'chat' | 'threads'
  /** Context the user added (the + Add menu, @-mentions). */
  added: ContextItem[]
  /** Default context the user removed, by chipKey. Cleared by New chat. */
  removed: string[]

  send: (req: Omit<AskRequest, 'thread_id'>) => Promise<void>
  stop: () => void
  newChat: () => void
  openThread: (id: number) => Promise<void>
  setFeedback: (id: string, value: Feedback) => Promise<void>
  setDeep: (deep: boolean) => void
  setView: (view: 'chat' | 'threads') => void
  addContext: (c: ContextItem) => void
  removeContext: (c: ContextItem) => void
}

export const chipKey = (c: Pick<ContextItem, 'kind' | 'id'>) => `${c.kind}:${c.id}`

let controller: AbortController | null = null

/** Rebuild the on-screen messages from a saved thread. */
export function fromStored(messages: StoredMessage[]): ChatMessage[] {
  const out: ChatMessage[] = []
  let prompt = ''
  messages.forEach((m, i) => {
    if (m.role === 'user') {
      prompt = m.text
      out.push({ id: `u${m.id}`, role: 'user', text: m.text })
      // A question with no saved answer after it was stopped mid-way.
      if (messages[i + 1]?.role !== 'assistant') out.push({ id: `s${m.id}`, role: 'stopped', steps: null })
      return
    }
    const r = m.result
    if (r.kind === 'done') {
      out.push({ id: `a${m.id}`, role: 'answer', prompt, blocks: m.blocks, steps: r.steps, elapsedMs: r.elapsed_ms, runId: r.run_id ?? null, messageId: m.id, feedback: m.feedback })
    } else if (r.kind === 'no_data') {
      out.push({ id: `a${m.id}`, role: 'nodata', title: r.title, message: r.message, oldestRunId: r.oldest_run_id ?? null, prompt })
    } else {
      out.push({ id: `a${m.id}`, role: 'error', title: r.title, message: r.message, prompt })
    }
  })
  return out
}

export const useChat = create<ChatState>()((set, get) => ({
  messages: [],
  threadId: null,
  busy: false,
  deep: false,
  view: 'chat',
  added: [],
  removed: [],

  send: async (req) => {
    if (get().busy || !req.text.trim()) return
    const n = Date.now()
    const thinkId = `k${n}`
    const answerId = `a${n}`
    set((s) => ({
      busy: true,
      view: 'chat',
      messages: [...s.messages, { id: `u${n}`, role: 'user', text: req.text }, { id: thinkId, role: 'thinking', steps: [] }],
    }))
    const ctl = new AbortController()
    controller = ctl
    const patch = (id: string, fn: (m: ChatMessage) => ChatMessage) => set((s) => ({ messages: s.messages.map((m) => (m.id === id ? fn(m) : m)) }))
    const blocks: AnswerBlock[] = []
    let steps: string[] = []
    let settled = false
    try {
      for await (const ev of ask({ ...req, thread_id: get().threadId }, ctl.signal)) {
        switch (ev.event) {
          case 'thread':
            set({ threadId: ev.data.id })
            break
          case 'step':
            steps = [...steps, ev.data.text]
            patch(thinkId, (m) => (m.role === 'thinking' ? { ...m, steps } : m))
            break
          case 'block':
            blocks.push(ev.data)
            break
          case 'done':
            settled = true
            patch(thinkId, () => ({ id: answerId, role: 'answer', prompt: req.text, blocks, steps: ev.data.steps, elapsedMs: ev.data.elapsed_ms, runId: ev.data.run_id ?? null, messageId: null, feedback: null }))
            break
          case 'error':
            settled = true
            patch(thinkId, () =>
              ev.data.kind === 'no_data'
                ? { id: answerId, role: 'nodata', title: ev.data.title, message: ev.data.message, oldestRunId: ev.data.oldest_run_id ?? null, prompt: req.text }
                : { id: answerId, role: 'error', title: ev.data.title, message: ev.data.message, prompt: req.text },
            )
            break
          case 'saved':
            patch(answerId, (m) => (m.role === 'answer' ? { ...m, messageId: ev.data.message_id } : m))
            break
        }
      }
      if (!settled) {
        patch(thinkId, () => ({ id: answerId, role: 'error', title: 'The answer stopped early', message: 'The server closed the stream before the answer finished. Nothing was saved.', prompt: req.text }))
      }
    } catch (e) {
      if (ctl.signal.aborted) patch(thinkId, () => ({ id: thinkId, role: 'stopped', steps: steps.length }))
      else patch(thinkId, () => ({ id: answerId, role: 'error', title: 'Could not reach the dashboard server', message: e instanceof Error ? e.message : String(e), prompt: req.text }))
    } finally {
      if (controller === ctl) controller = null
      set({ busy: false })
    }
  },

  stop: () => controller?.abort(),

  newChat: () => {
    controller?.abort()
    set({ messages: [], threadId: null, busy: false, view: 'chat', added: [], removed: [] })
  },

  openThread: async (id) => {
    controller?.abort()
    const t = await fetchThread(id)
    const lastContext = [...t.messages].reverse().find((m): m is Extract<StoredMessage, { role: 'user' }> => m.role === 'user')?.context ?? []
    set({ messages: fromStored(t.messages), threadId: t.id, view: 'chat', added: lastContext.filter((c) => c.kind !== 'tab'), removed: [] })
  },

  setFeedback: async (id, value) => {
    const m = get().messages.find((x) => x.id === id)
    if (m?.role !== 'answer' || m.messageId == null) return
    const before = m.feedback
    const put = (feedback: Feedback) => set((s) => ({ messages: s.messages.map((x) => (x.id === id && x.role === 'answer' ? { ...x, feedback } : x)) }))
    put(value)
    try {
      await sendFeedback(m.messageId, value)
    } catch (e) {
      put(before)
      throw e
    }
  },

  setDeep: (deep) => set({ deep }),
  setView: (view) => set({ view }),
  addContext: (c) => set((s) => (s.added.some((x) => chipKey(x) === chipKey(c)) ? s : { added: [...s.added, c], removed: s.removed.filter((k) => k !== chipKey(c)) })),
  removeContext: (c) => set((s) => ({ added: s.added.filter((x) => chipKey(x) !== chipKey(c)), removed: [...s.removed, chipKey(c)] })),
}))
