import { useId, useState, type RefObject } from 'react'
import { Button, Icon, OptionList, Popover, Spacer, Stack, Switch, Text, TextAreaField, useListNav } from '@/design'
import { matchReferences, mentionQuery, type Reference } from './context'

/** The question field: Enter sends, Shift+Enter is a new line, `@` opens
 *  references to runs, steps and findings. While an answer streams, Send
 *  becomes Stop. */
export function Composer({ references, busy, deep, onDeep, onSend, onStop, onMention, textareaRef }: { references: Reference[]; busy: boolean; deep: boolean; onDeep: (on: boolean) => void; onSend: (text: string) => void; onStop: () => void; onMention: (r: Reference) => void; textareaRef: RefObject<HTMLTextAreaElement | null> }) {
  const [text, setText] = useState('')
  const [dismissed, setDismissed] = useState<string | null>(null)
  const listId = useId()
  const query = mentionQuery(text)
  const matches = query == null || query === dismissed ? [] : matchReferences(references, query)
  const open = matches.length > 0

  const pick = (i: number) => {
    const r = matches[i]
    if (!r || query == null) return
    setText(text.slice(0, text.length - query.length - 1) + `@${r.handle} `)
    onMention(r)
    textareaRef.current?.focus()
  }
  const nav = useListNav(matches.length, { onPick: pick, onClose: () => setDismissed(query) })

  const send = () => {
    if (busy || !text.trim()) return
    onSend(text.trim())
    setText('')
  }
  const insertAt = () => {
    setText((t) => t + (t && !t.endsWith(' ') ? ' @' : '@'))
    setDismissed(null)
    textareaRef.current?.focus()
  }

  return (
    <Stack gap={8}>
      <Popover open={open} onClose={() => setDismissed(query)} placement="above" inset={14}>
        <OptionList
          id={listId}
          label="References"
          active={nav.active}
          onPick={pick}
          onHover={nav.setActive}
          options={matches.map((r) => ({ key: `${r.kind}:${r.handle}`, label: `@${r.handle}`, meta: r.meta }))}
        />
      </Popover>
      <TextAreaField
        label="Message Copilot"
        placeholder="Ask about runs, steps or findings. @ to reference."
        textareaRef={textareaRef}
        value={text}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? `${listId}-${nav.active}` : undefined}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (open && nav.onKeyDown(e)) return
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            send()
          }
        }}
        footer={
          <>
            <Switch checked={deep} onChange={onDeep} label="Deep analysis" />
            <Button variant="quiet" aria-label="Mention a run, step or finding" title="Mention a run, step or finding" onClick={insertAt}>
              @
            </Button>
            <Spacer />
            {busy ? (
              <Button variant="secondary" size="sm" onClick={onStop} aria-label="Stop generating">
                <Icon name="stop" size={12} />
                Stop
              </Button>
            ) : (
              <Button variant="primary" size="sm" disabled={!text.trim()} onClick={send} aria-label="Send">
                Send ↵
              </Button>
            )}
          </>
        }
      />
      <Text variant="caption" as="p">
        Answers are computed from the run data on this dashboard, by rules rather than a language model. Verify against the traces before acting.
      </Text>
    </Stack>
  )
}
