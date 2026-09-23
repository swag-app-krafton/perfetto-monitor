/** The spacing scale: a 4px base with the half-steps the design uses. Layout
 *  props take one of these, so an off-scale gap is a type error. */
export const SPACE = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 48] as const
export type Space = (typeof SPACE)[number]
