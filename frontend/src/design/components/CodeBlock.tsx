import { useId, useState } from 'react'
import { Icon } from './Icon'
import s from './CodeBlock.module.css'

/** Code on the console surface: a header with the language and a Copy
 *  button, and a body that can collapse. Always dark, in both themes. */
export function CodeBlock({ code, lang, defaultOpen = true, onCopy }: { code: string; lang: string; defaultOpen?: boolean; onCopy?: (code: string) => void }) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  const copy = () => {
    void navigator.clipboard?.writeText(code).catch(() => undefined)
    onCopy?.(code)
  }
  return (
    <div className={s.block}>
      <div className={s.head}>
        <button type="button" className={s.toggle} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
          <Icon name={open ? 'chevronDown' : 'chevronRight'} size={12} />
          {lang}
        </button>
        <button type="button" className={s.copy} onClick={copy} aria-label={`Copy ${lang}`}>
          Copy
        </button>
      </div>
      {open && (
        <pre id={id} className={s.code}>
          {code}
        </pre>
      )}
    </div>
  )
}
