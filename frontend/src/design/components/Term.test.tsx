import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BarList } from '../charts/BarList'
import { Term } from './Term'
import { TermList } from './TermList'

describe('Term', () => {
  it('is just the name when there is no description', () => {
    render(<Term>bind_application</Term>)
    expect(screen.getByText('bind_application')).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('puts the description behind a ? named for the term', async () => {
    render(<Term description="The new process loading the app.">bind_application</Term>)
    const tip = screen.getByRole('button', { name: 'What is bind_application?' })
    expect(screen.queryByRole('tooltip')).toBeNull()
    await userEvent.hover(tip)
    expect(screen.getByRole('tooltip')).toHaveTextContent('The new process loading the app.')
  })

  it('keeps the ? beside a name that is itself a control', async () => {
    const onToggle = vi.fn()
    render(
      <Term description="What the step covers." label="layout_inflate">
        <button type="button" onClick={onToggle}>
          layout_inflate
        </button>
      </Term>,
    )
    const toggle = screen.getByRole('button', { name: 'layout_inflate' })
    const tip = screen.getByRole('button', { name: 'What is layout_inflate?' })
    expect(toggle.contains(tip)).toBe(false)
    await userEvent.click(tip)
    expect(onToggle).not.toHaveBeenCalled()
  })
})

describe('TermList', () => {
  it('shows each description under its name, with the figures beside it', () => {
    render(
      <TermList
        label="Startup steps"
        items={[
          { key: 'a', term: 'process_start', description: 'Android creating the process.', values: ['+0.0 ms', '3.8 ms'] },
          { key: 'b', term: 'activity_resume', values: ['+291.2 ms', '51.3 ms'] },
        ]}
      />,
    )
    const rows = within(screen.getByRole('list', { name: 'Startup steps' })).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('process_start')
    expect(rows[0]).toHaveTextContent('Android creating the process.')
    expect(rows[0]).toHaveTextContent('3.8 ms')
    expect(rows[1]).toHaveTextContent('activity_resume')
    expect(rows[1]).toHaveTextContent('51.3 ms')
  })
})

describe('BarList', () => {
  it('offers a ? only for items that have a description', () => {
    render(
      <BarList
        label="CPU by thread"
        unit="%"
        items={[
          { label: 'UI Thread', value: 30, description: "The app's main thread." },
          { label: 'sync-worker', value: 2 },
        ]}
      />,
    )
    expect(screen.getByRole('button', { name: 'What is UI Thread?' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'What is sync-worker?' })).toBeNull()
  })
})
