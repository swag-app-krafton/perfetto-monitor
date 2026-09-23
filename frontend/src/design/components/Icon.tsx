import type { SVGProps } from 'react'
import s from './Icon.module.css'

/** Inline icons from the handoff. `currentColor` unless noted. */
const paths = {
  sparkle: <path d="M12 1l2.2 6.8L21 10l-6.8 2.2L12 19l-2.2-6.8L3 10l6.8-2.2z" fill="currentColor" stroke="none" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  maximise: <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />,
  restore: <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4 4" />
    </>
  ),
  thumbUp: <path d="M7 10v10H4V10h3zm0 0l4-7c1.5 0 2.5 1 2.2 2.6L12.6 9H19a2 2 0 012 2.3l-1.3 7A2 2 0 0117.7 20H7" />,
  thumbDown: <path d="M17 14V4h3v10h-3zm0 0l-4 7c-1.5 0-2.5-1-2.2-2.6l.6-3.4H5a2 2 0 01-2-2.3l1.3-7A2 2 0 016.3 4H17" />,
  menu: <path d="M3 6h18M3 12h18M3 18h18" />,
  sparkles: (
    <>
      <path d="M12 1l2.2 6.8L21 10l-6.8 2.2L12 19l-2.2-6.8L3 10l6.8-2.2z" fill="currentColor" stroke="none" />
      <path d="M19 15l.9 2.6 2.6.9-2.6.9L19 22l-.9-2.6-2.6-.9 2.6-.9z" fill="currentColor" stroke="none" />
    </>
  ),
  stop: <rect x="7" y="7" width="10" height="10" fill="currentColor" stroke="none" />,
  chevronRight: <path d="M9 6l6 6-6 6" />,
  chevronDown: <path d="M6 9l6 6 6-6" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  external: <path d="M8 16L17 7M9 7h8v8" />,
  arrowRight: <path d="M5 12h14M13 6l6 6-6 6" />,
} as const

export type IconName = keyof typeof paths

/** `tone` colours the icon; without it the icon takes the text colour. */
export function Icon({ name, size = 16, tone, className, ...rest }: { name: IconName; size?: number; tone?: 'accent' | 'muted' | 'pass' | 'warn' | 'fail' } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      className={[tone && s[tone], className].filter(Boolean).join(' ') || undefined}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {paths[name]}
    </svg>
  )
}
