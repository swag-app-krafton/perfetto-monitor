import s from './Primitives.module.css'

/** A small colour key: a legend square, a series dot, or a live indicator.
 *  `pulse` is the recording pulse (dropped under reduced motion). Decorative
 *  unless given a `label`. */
export function Swatch({ color, size = 10, shape = 'square', pulse, label }: { color: string; size?: number; shape?: 'square' | 'circle'; pulse?: boolean; label?: string }) {
  return (
    <span
      className={[s.swatch, s[shape === 'circle' ? 'circle' : 'square'], pulse && s.pulse].filter(Boolean).join(' ')}
      style={{ width: size, height: size, background: color }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  )
}
