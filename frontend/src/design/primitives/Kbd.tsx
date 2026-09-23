import type { ReactNode } from 'react'
import s from './Primitives.module.css'

/** A keycap, e.g. the ⌘K hint on the Copilot button. Inherits its colour. */
export const Kbd = ({ children }: { children: ReactNode }) => <kbd className={s.kbd}>{children}</kbd>
