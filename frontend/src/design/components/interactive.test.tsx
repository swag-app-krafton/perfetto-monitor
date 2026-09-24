import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useSort } from '../hooks/useSort'
import { Chip } from './Chip'
import { ChoiceList } from './ChoiceList'
import { RowAction, SortTh, Table } from './DataTable'
import { Disclosure } from './Disclosure'
import { ExpandableTable } from './ExpandableTable'
import { Menu } from './Menu'
import { Switch } from './Switch'
import { Term } from './Term'

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

describe('ExpandableTable', () => {
  const ROWS = [
    { name: 'bind_application', dur: 190 },
    { name: 'activity_start', dur: 96 },
  ]
  const Demo = () => {
    const [open, setOpen] = useState<string | null>(null)
    const { sorted, sort, toggle } = useSort(ROWS, (r, k: 'name' | 'dur') => r[k], { key: 'dur', dir: 'desc' })
    return (
      <ExpandableTable
        label="Steps"
        minWidth={400}
        columns={[
          { key: 'name', sortKey: 'name', label: 'Step', width: '1fr' },
          { key: 'dur', sortKey: 'dur', label: 'Duration', width: '90px', align: 'right' },
        ]}
        rows={sorted}
        rowKey={(r) => r.name}
        toggleLabel={(r) => r.name}
        openKey={open}
        onToggle={(k) => setOpen(open === k ? null : k)}
        sort={{ ...sort, onSort: toggle }}
        cells={(r) => [
          <Term key="name" description={`What ${r.name} covers.`}>
            {r.name}
          </Term>,
          `${r.dur} ms`,
        ]}
        detail={(r) => `Detail for ${r.name}`}
      />
    )
  }

  it('opens a row from its toggle and says so', async () => {
    render(<Demo />)
    const toggle = screen.getByRole('button', { name: 'bind_application' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Detail for bind_application')).toBeNull()
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Detail for bind_application')).toBeVisible()
    await userEvent.click(toggle)
    expect(screen.queryByText('Detail for bind_application')).toBeNull()
  })

  it('keeps a cell\'s own control separate from the row toggle', async () => {
    render(<Demo />)
    await userEvent.click(screen.getByRole('button', { name: 'What is bind_application?' }))
    expect(screen.getByRole('button', { name: 'bind_application' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('sorts by a column and marks the header', async () => {
    render(<Demo />)
    // Row order, read from the rows' toggles (the "?" tips are expandable buttons too).
    const names = () =>
      screen
        .getAllByRole('button', { expanded: false })
        .map((b) => b.getAttribute('aria-label'))
        .filter((n) => !n?.startsWith('What is'))
    expect(names()[0]).toBe('bind_application')
    await userEvent.click(screen.getByRole('button', { name: /Sort by Step/ }))
    expect(screen.getByRole('columnheader', { name: /Step/ })).toHaveAttribute('aria-sort', 'descending')
    await userEvent.click(screen.getByRole('button', { name: /Sort by Step/ }))
    expect(screen.getByRole('columnheader', { name: /Step/ })).toHaveAttribute('aria-sort', 'ascending')
    expect(names()[0]).toBe('activity_start')
  })
})

describe('ChoiceList', () => {
  const Demo = () => {
    const [v, setV] = useState('a')
    return (
      <ChoiceList
        label="Package"
        value={v}
        onChange={setV}
        options={[
          { value: 'a', title: 'App A', description: 'com.a' },
          { value: 'b', title: 'App B' },
          { value: 'c', title: 'App C' },
        ]}
      />
    )
  }

  it('is one tab stop, and the arrow keys move the choice', async () => {
    render(<Demo />)
    const [a, b, c] = screen.getAllByRole('radio')
    expect(a).toHaveAttribute('aria-checked', 'true')
    expect(b).toHaveAttribute('tabindex', '-1')
    await userEvent.tab()
    expect(a).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    expect(b).toHaveAttribute('aria-checked', 'true')
    expect(b).toHaveFocus()
    await userEvent.keyboard('{ArrowUp}{ArrowUp}')
    expect(c).toHaveAttribute('aria-checked', 'true')
  })

  it('picks on click', async () => {
    render(<Demo />)
    await userEvent.click(screen.getByRole('radio', { name: /App C/ }))
    expect(screen.getByRole('radio', { name: /App C/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: /App A/ })).toHaveAttribute('aria-checked', 'false')
  })
})

describe('Table with SortTh and RowAction', () => {
  it('sorts from the header and picks a row from its action', async () => {
    const onPick = vi.fn()
    const ROWS = [
      { id: 80, ttid: 381 },
      { id: 81, ttid: 375 },
    ]
    const Demo = () => {
      const { sorted, sort, toggle } = useSort(ROWS, (r, k: 'id' | 'ttid') => r[k], { key: 'id', dir: 'desc' })
      return (
        <Table minWidth={300} density="dense" label="Runs">
          <thead>
            <tr>
              <SortTh label="Run" sortKey="id" sort={sort} onSort={toggle} />
              <SortTh label="TTID" sortKey="ttid" sort={sort} onSort={toggle} align="right" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.id}>
                <td>
                  <RowAction onClick={() => onPick(r.id)} aria-label={`Show run #${r.id}`}>
                    #{r.id}
                  </RowAction>
                </td>
                <td>{r.ttid} ms</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )
    }
    render(<Demo />)
    expect(screen.getByRole('columnheader', { name: /Run/ })).toHaveAttribute('aria-sort', 'descending')
    expect(screen.getByRole('columnheader', { name: /TTID/ })).toHaveAttribute('aria-sort', 'none')
    await userEvent.click(screen.getByRole('button', { name: /Sort by TTID/ }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('#80')
    await userEvent.click(screen.getByRole('button', { name: 'Show run #81' }))
    expect(onPick).toHaveBeenCalledWith(81)
  })
})
