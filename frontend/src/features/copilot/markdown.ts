import type { AnswerBlock } from './types'

const DIFF = { worse: '▲', better: '▼', same: '' } as const

/** An answer as Markdown, for Copy and Export .md. Citations become links
 *  to the dashboard routes they point at. */
export function toMarkdown(prompt: string, blocks: AnswerBlock[], origin = ''): string {
  const parts = [`> ${prompt.replace(/\n/g, '\n> ')}`]
  for (const b of blocks) {
    switch (b.type) {
      case 'verdict':
        parts.push(`**${b.label}** ${b.text}`)
        break
      case 'heading':
        parts.push(`### ${b.text}`)
        break
      case 'para':
        parts.push(b.text)
        break
      case 'table':
        parts.push(
          [
            `| ${b.cols.join(' | ')} |`,
            `|${b.cols.map((_, i) => (i === 0 ? ' --- ' : ' ---: ')).join('|')}|`,
            ...b.rows.map((r) => `| ${r.cells.map((c, i) => (i === r.cells.length - 1 && DIFF[r.tag] ? `${DIFF[r.tag]} ${c}` : c)).join(' | ')} |`),
          ].join('\n'),
        )
        break
      case 'bars':
        parts.push(`${b.title}${b.budget != null ? ` (North Star target ${b.budget} ${b.unit})` : ''}: ${b.labels.map((l, i) => `${l} ${b.values[i] ?? '–'}`).join(', ')}`)
        break
      case 'code':
        parts.push(`\`\`\`${b.lang === 'Markdown' ? 'md' : b.lang.toLowerCase().includes('sql') ? 'sql' : ''}\n${b.code}\n\`\`\``)
        break
      case 'cites':
        parts.push(`Sources: ${b.items.map((c) => `[${c.label}](${origin}${c.path})`).join(', ')}`)
        break
    }
  }
  return parts.join('\n\n') + '\n'
}
