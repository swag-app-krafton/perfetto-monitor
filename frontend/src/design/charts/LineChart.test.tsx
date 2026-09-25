import { fireEvent, render, screen } from '@testing-library/react'
import { LineChart } from './LineChart'
import { niceTicks } from './scale'

describe('LineChart', () => {
  it('picks nice 1/2/5 ticks', () => {
    expect(niceTicks(0, 1035)).toEqual([0, 500, 1000])
    expect(niceTicks(300, 470)).toEqual([300, 350, 400, 450])
    expect(niceTicks(3.2, 7.9)).toEqual([4, 5, 6, 7])
  })

  it('shows the empty message when every series is toggled off', () => {
    render(
      <LineChart
        label="t"
        labels={['#1', '#2']}
        series={[
          { name: 'A', color: 'red', values: [1, 2] },
          { name: 'B', color: 'blue', values: [2, null] },
        ]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /A/ }))
    fireEvent.click(screen.getByRole('button', { name: /B/ }))
    expect(screen.getByText('No series selected')).toBeInTheDocument()
  })

  it('reads values from the keyboard, and says so for a gap', () => {
    render(<LineChart label="TTID" labels={['#1', '#2']} unit="ms" series={[{ name: 'TTID', color: 'red', values: [400, null] }]} />)
    const plot = screen.getByRole('img', { name: /TTID/ })
    fireEvent.keyDown(plot, { key: 'ArrowRight' })
    expect(screen.getByText('400 ms')).toBeInTheDocument()
    fireEvent.keyDown(plot, { key: 'ArrowRight' })
    expect(screen.getByText('not measured')).toBeInTheDocument()
  })

  it('draws reference lines, and hides one with the series it belongs to', () => {
    render(
      <LineChart
        label="t"
        labels={['2.3', '2.4']}
        unit="ms"
        budget={420}
        series={[
          { name: 'V2514', color: 'red', values: [400, 410] },
          { name: 'Pixel 7', color: 'blue', values: [500, 520] },
        ]}
        references={[
          { value: 390, label: 'V2514 benchmark #3', series: 'V2514', color: 'red', style: 'dotted' },
          { value: 480, label: 'Pixel 7 benchmark #9', series: 'Pixel 7', color: 'blue', style: 'dotted' },
        ]}
      />,
    )
    expect(screen.getByText('North Star 420 ms')).toBeInTheDocument()
    expect(screen.getByText('V2514 benchmark #3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /V2514/ }))
    expect(screen.queryByText('V2514 benchmark #3')).not.toBeInTheDocument()
    expect(screen.getByText('Pixel 7 benchmark #9')).toBeInTheDocument()
    expect(screen.getByText('North Star 420 ms')).toBeInTheDocument()
  })

  it('shows the note for a point in the tooltip, never for a gap', () => {
    render(<LineChart label="Startup" labels={['2.3', '2.4']} unit="ms" series={[{ name: 'V2514', color: 'red', values: [400, null], notes: ['median of 3 runs', 'no runs'] }]} />)
    const plot = screen.getByRole('img', { name: /Startup/ })
    fireEvent.keyDown(plot, { key: 'ArrowRight' })
    expect(screen.getByText(/median of 3 runs/)).toBeInTheDocument()
    fireEvent.keyDown(plot, { key: 'ArrowRight' })
    expect(screen.getByText('not measured')).toBeInTheDocument()
    expect(screen.queryByText(/no runs/)).not.toBeInTheDocument()
  })
})
