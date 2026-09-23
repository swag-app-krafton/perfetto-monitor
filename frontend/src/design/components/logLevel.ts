export interface LogLine {
  t: number
  text: string
}
export type LogLevel = 'INFO' | 'WARN' | 'ERROR'

/** Level from the line's own prefix, as the job runner writes them. */
export const levelOf = (text: string): LogLevel =>
  /^(ERROR|FATAL)\b/i.test(text) ? 'ERROR' : /^(warning|note|WARN)\b/i.test(text) ? 'WARN' : 'INFO'
