import type { Diff, Tone } from '@/design'

/** A place on the dashboard an answer drew from. The server supplies the
 *  route and the highlight target, so the client never maps kinds to tabs. */
export interface Citation {
  kind: 'run' | 'finding' | 'step' | 'chart' | 'screen' | 'stress' | 'compare'
  id: string | number
  label: string
  path: string
  focus: string
}

/** The blocks an answer is made of, in the order the engine returns them. */
export type AnswerBlock =
  | { type: 'verdict'; tone: Tone; label: string; text: string }
  | { type: 'heading'; text: string }
  | { type: 'para'; text: string }
  | { type: 'table'; cols: string[]; rows: { cells: string[]; tag: Diff }[] }
  | { type: 'bars'; title: string; unit: string; labels: string[]; values: (number | null)[]; budget: number | null }
  | { type: 'code'; lang: string; open: boolean; code: string }
  | { type: 'cites'; items: Citation[] }

/** One item of context sent with every question. */
export interface ContextItem {
  kind: 'tab' | 'run' | 'benchmark' | 'step' | 'finding'
  id: string | number
  label: string
}

export type Feedback = 'up' | 'down' | null

export type ChatMessage =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'thinking'; steps: string[] }
  /** steps is null for a saved thread, where the count is not recorded. */
  | { id: string; role: 'stopped'; steps: number | null }
  | { id: string; role: 'error'; title: string; message: string; prompt: string }
  | { id: string; role: 'nodata'; title: string; message: string; oldestRunId: number | null; prompt: string }
  | {
      id: string
      role: 'answer'
      prompt: string
      blocks: AnswerBlock[]
      steps: string[]
      elapsedMs: number
      runId: number | null
      /** The saved message's id, once the server confirms it (pin, feedback). */
      messageId: number | null
      feedback: Feedback
    }

export type AnswerMessage = Extract<ChatMessage, { role: 'answer' }>

/** Server events on /api/copilot/ask. */
export type CopilotEvent =
  | { event: 'thread'; data: { id: number } }
  | { event: 'step'; data: { text: string } }
  | { event: 'block'; data: AnswerBlock }
  | { event: 'done'; data: { elapsed_ms: number; steps: string[]; run_id: number } }
  | { event: 'error'; data: { kind: 'no_data' | 'internal'; title: string; message: string; oldest_run_id?: number | null } }
  | { event: 'saved'; data: { message_id: number } }

export interface ThreadSummary {
  id: number
  title: string
  created: string
  updated: string
}

type DoneData = Extract<CopilotEvent, { event: 'done' }>['data']
type ErrorData = Extract<CopilotEvent, { event: 'error' }>['data']

/** A saved message as the server stores it. An assistant message's result is
 *  the final event: `done`, or the error's own kind. */
export type StoredMessage =
  | { id: number; role: 'user'; feedback: Feedback; text: string; context?: ContextItem[] }
  | { id: number; role: 'assistant'; feedback: Feedback; blocks: AnswerBlock[]; result: ({ kind: 'done' } & DoneData) | ErrorData }

export interface ThreadDetail extends ThreadSummary {
  messages: StoredMessage[]
}

/** An answer pinned to the Overview as a finding on its run. */
export interface CopilotPin {
  id: number
  message_id: number
  run_id: number
  title: string
  severity: 'high' | 'medium' | 'low'
  evidence: string
  created: string
}
