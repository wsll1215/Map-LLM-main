export const SSE_FAST_RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000] as const;
export const SSE_RECOVERY_DELAY_MS = 15000;
export const SSE_POLLING_ERROR_CODES = new Set([
  "sse_connection_limit",
  "sse_budget_unavailable",
]);

export function sseRetryDelayMs(attempt: number): number {
  const index = Math.max(1, Math.floor(attempt)) - 1;
  return SSE_FAST_RETRY_DELAYS_MS[index] ?? SSE_RECOVERY_DELAY_MS;
}

export function sseRetryDelayForStatus(status: number, attempt: number): number {
  return status === 429 ? SSE_RECOVERY_DELAY_MS : sseRetryDelayMs(attempt);
}

export function shouldEnterSsePolling(errorCode?: string): boolean {
  return Boolean(errorCode && SSE_POLLING_ERROR_CODES.has(errorCode));
}

export function isNonRetryableSseStatus(status: number): boolean {
  return status === 401 || status === 403 || status === 404;
}

export function isRetryableSseStatus(status: number): boolean {
  return status === 408 || status === 429 || status >= 500;
}

export function sseResponseErrorCode(status: number, errorCode: unknown): string | undefined {
  if (typeof errorCode === "string" && errorCode.trim()) return errorCode.trim();
  return status === 429 ? "sse_connection_limit" : undefined;
}
