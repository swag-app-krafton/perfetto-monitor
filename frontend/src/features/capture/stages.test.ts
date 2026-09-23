import { stageStates } from './CapturePage'

const log = (...texts: string[]) => texts.map((text, t) => ({ t, text }))

describe('capture stages', () => {
  it('marks what the log shows as done and the next as active', () => {
    expect(stageStates({ state: 'running', log: log('device: V2514 (Android 16)', 'force-stopping and cold-launching com.swag.pay for 10000ms…') })).toEqual([
      'done', 'done', 'active', 'pending', 'pending',
    ])
  })
  it('an error leaves no stage active', () => {
    expect(stageStates({ state: 'error', log: log('device: V2514', 'ERROR: adb died') })).toEqual(['done', 'pending', 'pending', 'pending', 'pending'])
  })
})
