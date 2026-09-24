export function makeCounter(limit: number) {
  let count = 0;
  return function increment() {
    count += 1;
    if (count > limit) {
      (function overflow() {
        throw new Error('counter overflow');
      })();
    }
    return count;
  };
}
