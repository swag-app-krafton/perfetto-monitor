import type { ReactNode } from 'react'
import { Text, type TextTone } from '../primitives/Text'
import s from './FlowList.module.css'

export interface FlowNode {
  key: string
  title: ReactNode
  meta?: ReactNode
  /** Nesting level from 1; each level indents the node one step. */
  depth?: number
  /** The connector to the next node, with what it cost ("Transition · 240 ms"). */
  link?: { label: ReactNode; tone?: TextTone }
}

/** Nodes in order with a connector between each and the next: a navigation
 *  stack, a pipeline, a sequence of states. Depth indents a node under the
 *  ones before it. */
export function FlowList({ nodes, label }: { nodes: FlowNode[]; label: string }) {
  return (
    <ol className={s.list} aria-label={label}>
      {nodes.map((n) => (
        <li key={n.key} style={{ marginLeft: `calc(${Math.max(0, (n.depth ?? 1) - 1)} * var(--flow-indent))` }}>
          <div className={s.node}>
            <span className={s.title}>{n.title}</span>
            {n.meta != null && <Text variant="meta">{n.meta}</Text>}
          </div>
          {n.link && (
            <div className={s.link}>
              <span className={s.linkBar} aria-hidden="true" />
              <Text variant="meta" tone={n.link.tone ?? 'muted'}>
                {n.link.label}
              </Text>
            </div>
          )}
        </li>
      ))}
    </ol>
  )
}
