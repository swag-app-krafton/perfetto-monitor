/** Who wrote a verdict, in the reader's words: the rules, or a model. */
export function verdictAuthor(model: string | null | undefined) {
  return !model || model === 'heuristic' ? 'the rules' : model
}
