// @@V2 const RETRIES = [100, 200, 400];
// @@V2 export function backoff(attempt: number): number {
// @@V2   return RETRIES[Math.min(attempt, RETRIES.length - 1)];
// @@V2 }
export async function loadProfile(id: string | null): Promise<{id: string}> {
  await Promise.resolve();
  if (!id) {
    throw new Error('profile id missing');
  }
  return {id};
}

export const handlers = {
  onPress(event: any): string {
    return event.target.value;
  },
};
