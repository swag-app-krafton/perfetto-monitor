import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Chip } from './Chip'
import { Disclosure } from './Disclosure'
import { Menu } from './Menu'
import { Switch } from './Switch'

describe('Switch', () => {
  it('is a switch that reports its state', async () => {
    const Demo = () => {
      const [on, setOn] = useState(false)
      return <Switch checked={on} onChange={setOn} label="Deep analysis" />
    }
    render(<Demo />)
    const sw = screen.getByRole('switch', { name: 'Deep analysis' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(sw)
    expect(sw).toHaveAttribute('aria-checked', 'true')
  })
})

describe('Disclosure', () => {
  it('reveals its detail and says so', async () => {
    render(<Disclosure summary="Queried run data · 2 steps">Loaded run #81 → Compared 5 steps</Disclosure>)
    const btn = screen.getByRole('button', { name: /Queried run data/ })
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText(/Loaded run #81/)).toBeNull()
    await userEvent.click(btn)
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/Loaded run #81/)).toBeVisible()
  })
})

describe('Chip', () => {
  it('names what its remove button removes', async () => {
    const onRemove = vi.fn()
    render(<Chip onRemove={onRemove} removeLabel="Remove Run #81 from context">Run #81</Chip>)
    await userEvent.click(screen.getByRole('button', { name: 'Remove Run #81 from context' }))
    expect(onRemove).toHaveBeenCalledOnce()
  })
})

describe('Menu', () => {
  const options = [
    { key: 'a', kind: 'Run', label: 'Run #80' },
    { key: 'b', kind: 'Step', label: 'Step: bind_application' },
    { key: 'c', kind: 'Finding', label: 'Finding F-1' },
  ]
  it('moves with the arrow keys, wraps, and picks with Enter', async () => {
    const onPick = vi.fn()
    render(
      <div style={{ position: 'relative' }}>
        <Menu open onClose={() => undefined} options={options} onPick={onPick} label="Add context" />
      </div>,
    )
    const opts = screen.getAllByRole('option')
    expect(opts[0]).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowUp}')
    expect(opts[2]).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onPick).toHaveBeenCalledWith(options[1])
  })

  it('closes on Escape and on a click outside', async () => {
    const onClose = vi.fn()
    render(
      <>
        <button type="button">outside</button>
        <div style={{ position: 'relative' }}>
          <Menu open onClose={onClose} options={options} onPick={() => undefined} label="Add context" />
        </div>
      </>,
    )
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: 'outside' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
