/** Status tones. Status is never colour alone: every tone has a glyph. */
export type Tone = 'pass' | 'warn' | 'fail' | 'neutral'

export const GLYPH: Record<Tone, string> = { pass: '✓', warn: '!', fail: '✕', neutral: '–' }

/** The CSS colour of a tone, for marks drawn with inline geometry. */
export const toneColor = (t: Tone) => (t === 'neutral' ? 'var(--tx3)' : `var(--${t})`)
