// @@V2 export function clamp(value: number, low: number, high: number): number {
// @@V2   const bounded = Math.min(Math.max(value, low), high);
// @@V2   return Number.isFinite(bounded) ? bounded : low;
// @@V2 }
export function divide(a: number, b: number): number {
  if (b === 0) {
    throw new RangeError('divide by zero');
  }
  return a / b;
}

export function average(values: number[]): number {
  function sum(xs: number[]): number {
    let total = 0;
    for (const x of xs) {
      total += x;
    }
    return total;
  }
  return divide(sum(values), values.length);
}
