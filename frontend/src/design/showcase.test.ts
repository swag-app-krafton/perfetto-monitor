/** The /design-system page is the design system's living reference, so every
 *  component the system exports must appear on it. A component added without
 *  a specimen fails here. */
const sources = import.meta.glob(['./**/*.tsx', '!./**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const page = import.meta.glob('../features/design-system/DesignSystemPage.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

// PascalCase exported functions and consts are components; ALL_CAPS ones are constants.
const components = Object.values(sources)
  .flatMap((src) => [...src.matchAll(/^export (?:function|const) ([A-Z][A-Za-z0-9]*)\b/gm)].map((m) => m[1]!))
  .filter((name) => name !== name.toUpperCase())

describe('design system reference page', () => {
  const text = Object.values(page)[0]!

  it('finds the components', () => {
    expect(components.length).toBeGreaterThan(50)
  })

  it.each(components)('shows %s', (name) => {
    expect(text).toMatch(new RegExp(`\\b${name}\\b`))
  })
})
