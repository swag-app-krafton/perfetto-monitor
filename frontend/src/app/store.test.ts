import { beforeEach, describe, expect, it } from 'vitest'
import { useUi } from './store'

describe('run in view', () => {
  beforeEach(() => useUi.setState({ app: 'com.swag.pay', path: 'cold', range: '30', runId: null }))

  it('keeps the chosen run while only the range changes', () => {
    useUi.getState().setRunId(72)
    useUi.getState().setFilters({ range: '10' })
    expect(useUi.getState().runId).toBe(72)
  })

  it('returns to the newest run when the app or path changes', () => {
    useUi.getState().setRunId(72)
    useUi.getState().setFilters({ path: 'warm' })
    expect(useUi.getState().runId).toBeNull()
    useUi.getState().setRunId(72)
    useUi.getState().setFilters({ app: 'com.phonepe.app', path: 'cold' })
    expect(useUi.getState().runId).toBeNull()
  })

  it('keeps it when the same app and path are set again (a link to a run in scope)', () => {
    useUi.getState().setRunId(72)
    useUi.getState().setFilters({ app: 'com.swag.pay', path: 'cold' })
    expect(useUi.getState().runId).toBe(72)
  })
})
