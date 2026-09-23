import { createRef } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Composer } from './Composer'
import type { Reference } from './context'

const refs: Reference[] = [
  { handle: '#81', kind: 'Run', meta: 'Run · Sep 23 · FAIL', item: { kind: 'run', id: 81, label: 'Run #81' } },
  { handle: 'bind_application', kind: 'Step', meta: 'Step · +9.7 ms', item: { kind: 'step', id: 'step:bind_application', label: 'Step: bind_application' } },
]

function setup(busy = false) {
  const onSend = vi.fn()
  const onStop = vi.fn()
  const onMention = vi.fn()
  render(<Composer references={refs} busy={busy} deep={false} onDeep={() => undefined} onSend={onSend} onStop={onStop} onMention={onMention} textareaRef={createRef()} />)
  return { onSend, onStop, onMention, field: screen.getByRole('textbox', { name: 'Message Copilot' }) }
}

describe('Composer', () => {
  it('sends on Enter and keeps Shift+Enter as a new line', async () => {
    const { onSend, field } = setup()
    await userEvent.type(field, 'Why did TTID{Shift>}{Enter}{/Shift}regress?')
    expect(onSend).not.toHaveBeenCalled()
    await userEvent.keyboard('{Enter}')
    expect(onSend).toHaveBeenCalledWith('Why did TTID\nregress?')
    expect(field).toHaveValue('')
  })

  it('does not send an empty question', async () => {
    const { onSend, field } = setup()
    await userEvent.type(field, '   {Enter}')
    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('completes an @-mention from the keyboard and adds it as context', async () => {
    const { onMention, onSend, field } = setup()
    await userEvent.type(field, 'Why did @bind')
    expect(screen.getByRole('option', { name: /@bind_application/ })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    expect(field).toHaveValue('Why did @bind_application ')
    expect(onMention).toHaveBeenCalledWith(refs[1])
    expect(onSend).not.toHaveBeenCalled()
  })

  it('offers Stop instead of Send while an answer streams', async () => {
    const { onStop } = setup(true)
    expect(screen.queryByRole('button', { name: 'Send' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Stop generating' }))
    expect(onStop).toHaveBeenCalledOnce()
  })
})
