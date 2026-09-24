import { useCallback, useEffect, useEffectEvent, useMemo, useRef } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { screenByPath } from '@/app/routes'
import { lanePath, useProfiler } from '@/app/profiler'
import { COPILOT_MAX, COPILOT_MIN, platformOf, useUi } from '@/app/store'
import { Avatar, DockPanel, Fab, Icon, IconButton, Kbd, ListButton, PanelBody, PanelFooter, PanelHeader, Stack, Text } from '@/design'
import { useScope } from '@/domain/scope'
import { focusHref } from '@/lib/highlight'
import { useViewportWidth } from '@/lib/useMediaQuery'
import { usePinMutations } from './api'
import { useChat } from './chat'
import { Composer } from './Composer'
import { activeContext, defaultContext, references } from './context'
import { ContextBar } from './ContextBar'
import { toMarkdown } from './markdown'
import { Message, type AnswerActions } from './Messages'
import { startersFor } from './starters'
import { Threads } from './Threads'
import type { AnswerMessage } from './types'

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

/** The Copilot: a floating button while closed, a docked panel while open.
 *  Rendered by the app shell beside the page. ⌘K / Ctrl+K toggles it from
 *  anywhere; Esc closes it. */
export function Copilot() {
  const { copilot: cp, setCopilot, copilotPrompt, showToast } = useUi()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const open = cp.open

  const toggle = useCallback(() => setCopilot({ open: !useUi.getState().copilot.open }), [setCopilot])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        toggle()
      } else if (e.key === 'Escape' && useUi.getState().copilot.open && !e.defaultPrevented && !document.querySelector('dialog[open]')) {
        // A modal (Run details) takes Esc for itself.
        setCopilot({ open: false })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle, setCopilot])

  // Opening puts the cursor in the composer.
  useEffect(() => {
    if (open) requestAnimationFrame(() => textareaRef.current?.focus())
  }, [open])

  if (!open) {
    return (
      <Fab onClick={() => setCopilot({ open: true })} aria-label={`Open Copilot (${isMac ? 'Command' : 'Control'} K)`}>
        <Icon name="sparkles" size={18} />
        Ask
        <Kbd>{isMac ? '⌘K' : 'Ctrl K'}</Kbd>
      </Fab>
    )
  }
  return <Panel textareaRef={textareaRef} prompt={copilotPrompt} showToast={showToast} />
}

function Panel({ textareaRef, prompt, showToast }: { textareaRef: React.RefObject<HTMLTextAreaElement | null>; prompt: { id: number; text: string } | null; showToast: (t: string) => void }) {
  const { copilot: cp, setCopilot } = useUi()
  const chat = useChat()
  const { scope } = useScope()
  const loc = useLocation()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { pin } = usePinMutations()
  const vw = useViewportWidth()
  const narrow = vw < 760
  const width = cp.maximised ? Math.min(760, Math.round(vw * 0.55)) : cp.width
  const screen = screenByPath(loc.pathname)
  // The page, whichever lane shows it: iOS screens reuse the trace pages.
  const tab = screen.page ?? screen.id
  const lane = useProfiler()
  const bodyRef = useRef<HTMLDivElement>(null)

  const refs = useMemo(() => references(scope), [scope])
  const context = activeContext(defaultContext(scope, screen), chat.added, chat.removed)
  const scopeReq = useMemo(
    () => ({ app: scope?.run?.app_pkg ?? undefined, path: scope?.run?.path_kind ?? undefined, platform: platformOf(lane) }),
    [scope, lane],
  )

  const send = (text: string) => void chat.send({ text, context, scope: scopeReq, deep: chat.deep })

  // A page asked a question ("Ask Copilot" on a finding): send it once, with
  // the context as it is now.
  const sendPrompt = useEffectEvent((text: string) => send(text))
  useEffect(() => {
    if (!prompt) return
    useUi.setState({ copilotPrompt: null })
    sendPrompt(prompt.text)
  }, [prompt])

  // Keep the newest message in view as the conversation grows.
  const last = chat.messages.at(-1)
  const progress = last?.role === 'thinking' ? last.steps.length : 0
  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [chat.messages.length, progress])

  const go = (href: string) => {
    // Citations name Android paths; they open in the lane in view.
    navigate(lanePath(lane, href))
    // Full screen on a phone: close so the highlighted target is visible.
    if (narrow) setCopilot({ open: false })
  }
  const actions: AnswerActions = {
    onCite: (c) => go(focusHref(c.path, c.focus)),
    onCopied: showToast,
    onCopy: (m) => {
      void navigator.clipboard?.writeText(toMarkdown(m.prompt, m.blocks, location.origin)).catch(() => undefined)
      showToast('Answer copied as Markdown')
    },
    onCompare: (m) => {
      const c = m.blocks.flatMap((b) => (b.type === 'cites' ? b.items : [])).find((x) => x.kind === 'compare')
      go(c ? focusHref(c.path, c.focus) : focusHref('/compare', 'compare'))
    },
    onPin: (m: AnswerMessage) => {
      if (m.messageId == null) return
      pin.mutate(m.messageId, {
        onSuccess: (p) => showToast(`Pinned to Overview as a finding on run #${p.run_id}`),
        onError: (e) => showToast(`Could not pin: ${e.message}`),
      })
    },
    onExport: (m) => {
      const name = `copilot-run-${m.runId ?? 'answer'}.md`
      const url = URL.createObjectURL(new Blob([toMarkdown(m.prompt, m.blocks, location.origin)], { type: 'text/markdown' }))
      const a = Object.assign(document.createElement('a'), { href: url, download: name })
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      showToast(`Exported ${name}`)
    },
    onFeedback: (m, value) => void chat.setFeedback(m.id, value).catch(() => showToast('Could not save feedback')),
  }

  const compare = tab === 'compare' ? { a: Number(params.get('a')) || null, b: Number(params.get('b')) || null } : undefined
  const starters = startersFor(tab, scope, compare)

  return (
    <DockPanel
      label="Copilot"
      width={width}
      fullscreen={narrow}
      resize={{ min: COPILOT_MIN, max: COPILOT_MAX, onResize: (w) => setCopilot({ width: w, maximised: false }) }}
    >
      <PanelHeader
        leading={<Avatar size={28} />}
        title="Copilot"
        subtitle={chat.deep ? 'Deep analysis · slower, cross-checks stress runs' : 'Fast · run data on this dashboard'}
        actions={
          <>
            <IconButton icon="clock" label="Conversation history" pressed={chat.view === 'threads'} onClick={() => chat.setView(chat.view === 'threads' ? 'chat' : 'threads')} />
            <IconButton icon="plus" label="New chat" onClick={chat.newChat} />
            {!narrow && <IconButton icon={cp.maximised ? 'restore' : 'maximise'} label={cp.maximised ? 'Restore panel width' : 'Maximise panel'} onClick={() => setCopilot({ maximised: !cp.maximised })} />}
            <IconButton icon="close" label="Close Copilot (Esc)" onClick={() => setCopilot({ open: false })} />
          </>
        }
      />
      <ContextBar items={context} references={refs} onAdd={chat.addContext} onRemove={chat.removeContext} />
      {chat.view === 'threads' ? (
        <Threads current={chat.threadId} onNew={chat.newChat} onOpen={(id) => void chat.openThread(id).catch((e: Error) => showToast(`Could not open the thread: ${e.message}`))} />
      ) : (
        <PanelBody ref={bodyRef} label="Conversation">
          {chat.messages.length === 0 && (
            <Stack gap={18}>
              <Stack gap={8}>
                <Text as="h3" variant="display">
                  Ask about this run.
                </Text>
                <Text as="p" variant="body">
                  I read the run data on this dashboard and cite the runs, steps and findings each answer comes from.
                </Text>
              </Stack>
              <Text variant="label">Suggested for {screen.label}</Text>
              <Stack gap={8}>
                {starters.map((t) => (
                  <ListButton key={t} title={t} trailing="→" onClick={() => send(t)} />
                ))}
              </Stack>
              <Text variant="small" tone="muted">
                Type{' '}
                <Text variant="small" tone="secondary" weight={700}>
                  @
                </Text>{' '}
                to reference a run, step or finding.
              </Text>
            </Stack>
          )}
          {chat.messages.map((m) => (
            <Message
              key={m.id}
              m={m}
              actions={actions}
              onRetry={send}
              onUseRun={(p, id) => send(p.replace(/#\d+/, `#${id}`))}
              onOpenHistory={() => go('/history')}
            />
          ))}
        </PanelBody>
      )}
      <PanelFooter>
        <Composer references={refs} busy={chat.busy} deep={chat.deep} onDeep={chat.setDeep} onSend={send} onStop={chat.stop} onMention={(r) => chat.addContext(r.item)} textareaRef={textareaRef} />
      </PanelFooter>
    </DockPanel>
  )
}
