import { fireEvent, render, screen } from '@testing-library/react'
import { LineChart, niceTicks } from './LineChart'

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
})
