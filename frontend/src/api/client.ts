/** A thin, typed fetch wrapper. Errors carry the server's own message when it
 *  sends one ({"error": "..."}), so the UI can show what actually went wrong. */

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Sent on every request. The server refuses a write without it (T-001): a
 *  page on another site can't send a custom header without a CORS preflight,
 *  and the server never approves one. */
export const WRITE_HEADERS = { 'Content-Type': 'application/json', 'X-Swagperf': '1' } as const

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { ...WRITE_HEADERS, ...(init?.headers ?? {}) },
  })
  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const msg =
      body && typeof body === 'object' && 'error' in body ? String((body as { error: unknown }).error) : res.statusText
    throw new ApiError(res.status, msg)
  }
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data: unknown = {}) => request<T>(path, { method: 'POST', body: JSON.stringify(data) }),
}
