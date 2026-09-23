import { useId, type ReactNode, type Ref, type TextareaHTMLAttributes } from 'react'
import { Icon } from './Icon'
import s from './Field.module.css'

export function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  const id = useId()
  return (
    <label className={s.field} htmlFor={id}>
      <span className={s.label}>{label}</span>
      <select id={id} className={s.select} value={value} onChange={(e) => onChange(e.target.value as T)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function SearchInput({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  label: string
}) {
  return (
    <div className={s.search}>
      <Icon name="search" size={14} />
      <input type="search" aria-label={label} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

/** A multi-line field with a toolbar row under it (the Copilot composer).
 *  The border turns accent while anything inside has focus. */
export function TextAreaField({
  label,
  footer,
  textareaRef,
  rows = 3,
  ...rest
}: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'aria-label'> & { label: string; footer?: ReactNode; textareaRef?: Ref<HTMLTextAreaElement> }) {
  return (
    <div className={s.area}>
      <textarea ref={textareaRef} rows={rows} aria-label={label} className={s.textarea} {...rest} />
      {footer && <div className={s.areaFooter}>{footer}</div>}
    </div>
  )
}
