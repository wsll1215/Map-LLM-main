import { apiErrorSchema } from "../types/api";

export type AuthStatus =
  | "initializing"
  | "authenticated"
  | "refreshing"
  | "connection_recovering"
  | "reauth_required"
  | "logged_out";

export class ApiRequestError extends Error {
  readonly status: number;
  readonly errorCode?: string;
  readonly retryable?: boolean;
  readonly nextAction?: string;
  readonly retryAfter?: number;
  readonly details: unknown;

  constructor(message: string, response: Response, body: Record<string, unknown>) {
    super(message);
    this.name = "ApiRequestError";
    this.status = response.status;
    this.errorCode = typeof body.error_code === "string" ? body.error_code : undefined;
    this.retryable = typeof body.retryable === "boolean" ? body.retryable : undefined;
    this.nextAction = typeof body.next_action === "string" ? body.next_action : undefined;
    this.retryAfter = typeof body.retry_after === "number" ? body.retry_after : undefined;
    this.details = body.details;
  }
}

type TokenPayload = {
  access_token: string;
  expires_in: number;
  access_expires_at: string;
  refresh_expires_at: string;
};

type AuthChannelMessage =
  | { type: "refresh_claim"; tabId: string; claimId: string; expiresAt: number }
  | { type: "refresh_started"; tabId: string; leaseExpiresAt: number }
  | { type: "refresh_succeeded"; tabId: string; payload: TokenPayload }
  | { type: "refresh_failed"; tabId: string; errorCode?: string };

export const REFRESH_MIN_VALIDITY_SECONDS = 120;
const FAST_REFRESH_DELAYS_MS = [500, 1000, 2000, 4000, 8000] as const;
const REFRESH_RECOVERY_DELAY_MS = 15000;
const PEER_REFRESH_LEASE_MS = 15000;
const REFRESH_ELECTION_WINDOW_MS = 150;
const AUTH_ENDPOINTS = [
  "/accounts/api/tokens/",
  "/accounts/api/tokens/refresh/",
];

let accessToken: string | null = null;
let accessExpiresAt = 0;
let authInitialized = false;
let refreshPromise: Promise<string> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let peerRefreshing = false;
let peerRefreshUntil = 0;
let peerRefreshErrorCode: string | undefined;
let peerRefreshWaiters: Array<() => void> = [];
const refreshClaims = new Map<string, { claimId: string; expiresAt: number }>();
const tabId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
const authListeners = new Set<(status: AuthStatus) => void>();
let authStatus: AuthStatus = "initializing";
const authChannel = typeof BroadcastChannel !== "undefined"
  ? new BroadcastChannel("map-llm-auth-v1")
  : null;

if (authChannel) {
  authChannel.onmessage = ({ data }: MessageEvent<AuthChannelMessage>) => {
    if (!data || data.tabId === tabId) return;
    if (data.type === "refresh_claim") {
      if (data.expiresAt > Date.now()) {
        refreshClaims.set(data.tabId, { claimId: data.claimId, expiresAt: data.expiresAt });
      }
      return;
    }
    if (data.type === "refresh_started") {
      peerRefreshing = true;
      peerRefreshErrorCode = undefined;
      peerRefreshUntil = Math.max(data.leaseExpiresAt, Date.now() + 1000);
      return;
    }
    peerRefreshing = false;
    peerRefreshErrorCode = data.type === "refresh_failed" ? data.errorCode : undefined;
    peerRefreshUntil = 0;
    peerRefreshWaiters.splice(0).forEach((resolve) => resolve());
    if (data.type === "refresh_succeeded") {
      applyTokenPayload(data.payload);
      notifyAuth("authenticated");
    } else if (data.type === "refresh_failed" && isTerminalRefreshErrorCode(data.errorCode)) {
      clearAccessToken("reauth_required");
    }
  };
}

function notifyAuth(status: AuthStatus) {
  authStatus = status;
  authListeners.forEach((listener) => listener(status));
}

export function getAuthStatus(): AuthStatus {
  return authStatus;
}

export function subscribeAuth(listener: (status: AuthStatus) => void) {
  authListeners.add(listener);
  return () => {
    authListeners.delete(listener);
  };
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function clearAccessToken(status: AuthStatus = "logged_out") {
  if (refreshTimer !== null) clearTimeout(refreshTimer);
  refreshTimer = null;
  accessToken = null;
  accessExpiresAt = 0;
  notifyAuth(status);
}

function applyTokenPayload(payload: TokenPayload) {
  accessToken = payload.access_token;
  const parsedExpiry = Date.parse(payload.access_expires_at);
  accessExpiresAt = Number.isFinite(parsedExpiry)
    ? parsedExpiry
    : Date.now() + payload.expires_in * 1000;
  scheduleProactiveRefresh();
}

function scheduleProactiveRefresh() {
  if (refreshTimer !== null) clearTimeout(refreshTimer);
  if (!accessToken || typeof setTimeout === "undefined") return;
  const delay = Math.max(1000, accessExpiresAt - Date.now() - REFRESH_MIN_VALIDITY_SECONDS * 1000);
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    void refreshAccessToken().catch((error) => {
      if (!isTerminalRefreshError(error)) scheduleRefreshRecovery();
    });
  }, delay);
}

function scheduleRefreshRecovery(delay = REFRESH_RECOVERY_DELAY_MS) {
  if (refreshTimer !== null) clearTimeout(refreshTimer);
  if (typeof setTimeout === "undefined") return;
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    void refreshAccessToken().catch((error) => {
      if (isTerminalRefreshError(error)) return;
      scheduleRefreshRecovery();
    });
  }, Math.max(1000, delay));
}

function tokenIsFresh(minValiditySeconds: number) {
  return Boolean(accessToken) && accessExpiresAt - Date.now() > minValiditySeconds * 1000;
}

function csrfToken() {
  if (typeof document === "undefined") return "";
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("csrftoken="))
    ?.split("=")[1] ?? "";
}

function refreshRequestId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function isTerminalRefreshErrorCode(errorCode?: string) {
  return [
    "refresh_token_expired",
    "refresh_token_revoked",
    "refresh_token_reuse_detected",
    "refresh_token_invalid",
    "refresh_token_missing",
  ].includes(errorCode || "");
}

export function isTerminalRefreshError(error: unknown) {
  if (!(error instanceof ApiRequestError)) return false;
  return isTerminalRefreshErrorCode(error.errorCode);
}

export function isRetryableRefreshError(error: unknown) {
  if (!(error instanceof ApiRequestError)) return true;
  return error.retryable === true || error.status === 408 || error.status === 429 || error.status >= 500;
}

export function refreshRecoveryDelayMs(attempt: number) {
  const index = Math.max(1, Math.floor(attempt)) - 1;
  return FAST_REFRESH_DELAYS_MS[index] ?? REFRESH_RECOVERY_DELAY_MS;
}

export function refreshRetryDelayMs(error: unknown, attempt: number) {
  const backoff = refreshRecoveryDelayMs(attempt);
  if (!(error instanceof ApiRequestError) || typeof error.retryAfter !== "number") return backoff;
  const retryAfterMs = Math.min(60000, Math.max(0, error.retryAfter * 1000));
  return Math.max(backoff, retryAfterMs);
}

async function fetchRefreshToken(requestId: string): Promise<string> {
  notifyAuth("refreshing");
  const headers = new Headers({ Accept: "application/json", "X-Refresh-Request-Id": requestId });
  const csrf = csrfToken();
  if (csrf) headers.set("X-CSRFToken", decodeURIComponent(csrf));
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 10000);
  let response: Response;
  try {
    response = await fetch("/accounts/api/tokens/refresh/", {
      method: "POST",
      headers,
      credentials: "same-origin",
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiRequestError("登录状态服务响应超时，请稍后重试", new Response(null, { status: 408 }), {
        error_code: "refresh_temporarily_unavailable",
        retryable: true,
        retry_after: 1,
        next_action: "retry_refresh",
      });
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
  const body = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok || typeof body.access_token !== "string") {
    const message = typeof body.message === "string" ? body.message : `登录状态恢复失败 (${response.status})`;
    throw new ApiRequestError(message, response, body);
  }
  const payload = body as unknown as TokenPayload;
  applyTokenPayload(payload);
  notifyAuth("authenticated");
  return payload.access_token;
}

function waitForPeerRefresh() {
  if (!peerRefreshing || Date.now() >= peerRefreshUntil) {
    peerRefreshing = false;
    peerRefreshUntil = 0;
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      const index = peerRefreshWaiters.indexOf(finish);
      if (index >= 0) peerRefreshWaiters.splice(index, 1);
      resolve();
    };
    peerRefreshWaiters.push(finish);
    window.setTimeout(finish, Math.max(0, peerRefreshUntil - Date.now()));
  });
}

function cleanupRefreshClaims() {
  const now = Date.now();
  for (const [candidate, claim] of refreshClaims) {
    if (claim.expiresAt <= now) refreshClaims.delete(candidate);
  }
}

async function claimRefreshLease(): Promise<boolean> {
  if (!authChannel) return true;
  const claimId = refreshRequestId();
  const expiresAt = Date.now() + PEER_REFRESH_LEASE_MS;
  cleanupRefreshClaims();
  refreshClaims.set(tabId, { claimId, expiresAt });
  authChannel.postMessage({ type: "refresh_claim", tabId, claimId, expiresAt });
  await new Promise<void>((resolve) => window.setTimeout(resolve, REFRESH_ELECTION_WINDOW_MS));
  cleanupRefreshClaims();
  if (peerRefreshing && Date.now() < peerRefreshUntil) {
    refreshClaims.delete(tabId);
    await waitForPeerRefresh();
    return false;
  }
  const winner = [...refreshClaims.keys()].sort()[0];
  if (winner === tabId) {
    refreshClaims.delete(tabId);
    return true;
  }
  refreshClaims.delete(tabId);
  await waitForPeerRefresh();
  return false;
}

async function runRefreshSingleFlight(requestId: string): Promise<string> {
  const refresh = async () => {
    if (tokenIsFresh(REFRESH_MIN_VALIDITY_SECONDS)) return accessToken!;
    await waitForPeerRefresh();
    if (tokenIsFresh(REFRESH_MIN_VALIDITY_SECONDS)) return accessToken!;
    const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
    if (!locks && !(await claimRefreshLease())) {
      if (tokenIsFresh(REFRESH_MIN_VALIDITY_SECONDS)) return accessToken!;
      if (isTerminalRefreshErrorCode(peerRefreshErrorCode)) {
        const errorCode = peerRefreshErrorCode;
        peerRefreshErrorCode = undefined;
        throw new ApiRequestError("登录状态已失效，请重新登录", new Response(null, { status: 401 }), {
          error_code: errorCode,
          retryable: false,
        });
      }
      throw new Error("peer_refresh_failed");
    }
    const leaseExpiresAt = Date.now() + PEER_REFRESH_LEASE_MS;
    authChannel?.postMessage({ type: "refresh_started", tabId, leaseExpiresAt });
    try {
      const token = await fetchRefreshToken(requestId);
      authChannel?.postMessage({
        type: "refresh_succeeded",
        tabId,
        payload: {
          access_token: token,
          expires_in: Math.max(0, Math.round((accessExpiresAt - Date.now()) / 1000)),
          access_expires_at: new Date(accessExpiresAt).toISOString(),
          refresh_expires_at: "",
        },
      });
      return token;
    } catch (error) {
      if (isTerminalRefreshError(error)) clearAccessToken("reauth_required");
      else notifyAuth("connection_recovering");
      authChannel?.postMessage({
        type: "refresh_failed",
        tabId,
        errorCode: error instanceof ApiRequestError ? error.errorCode : undefined,
      });
      throw error;
    }
  };

  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (locks) return locks.request("map-auth-refresh", refresh);
  return refresh();
}

export async function refreshAccessToken(): Promise<string> {
  if (refreshPromise) return refreshPromise;
  const requestId = refreshRequestId();
  refreshPromise = (async () => {
    let lastError: unknown;
    for (let attempt = 0; attempt < FAST_REFRESH_DELAYS_MS.length; attempt += 1) {
      try {
        return await runRefreshSingleFlight(requestId);
      } catch (error) {
        lastError = error;
        if (!isRetryableRefreshError(error)) throw error;
        await new Promise<void>((resolve) => window.setTimeout(resolve, refreshRetryDelayMs(error, attempt + 1)));
      }
    }
    if (!isTerminalRefreshError(lastError)) scheduleRefreshRecovery();
    throw lastError instanceof Error ? lastError : new Error("登录状态恢复失败");
  })().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

export async function bootstrapAuth(): Promise<boolean> {
  notifyAuth("initializing");
  try {
    await refreshAccessToken();
    authInitialized = true;
    return true;
  } catch (error) {
    authInitialized = true;
    if (isTerminalRefreshError(error)) {
      clearAccessToken("logged_out");
      return false;
    }
    notifyAuth("connection_recovering");
    scheduleRefreshRecovery();
    return true;
  }
}

export async function ensureAccessToken(minValiditySeconds = REFRESH_MIN_VALIDITY_SECONDS) {
  if (tokenIsFresh(minValiditySeconds)) return accessToken!;
  return refreshAccessToken();
}

function isAuthEndpoint(url: string, method = "GET") {
  const path = url.split("?", 1)[0].replace(/\/$/, "");
  return AUTH_ENDPOINTS.some((endpoint) =>
    path === endpoint.replace(/\/$/, "") && method.toUpperCase() === "POST"
  );
}

function isLogoutEndpoint(url: string) {
  return url.startsWith("/accounts/api/tokens/current/");
}

function canRetryAfterAuth(init: RequestInit) {
  const method = (init.method || "GET").toUpperCase();
  if (method === "GET" || method === "HEAD") return true;
  if (method !== "POST") return false;
  const headers = new Headers(init.headers);
  return headers.has("Idempotency-Key") || headers.has("X-Message-Id");
}

function attachRequestHeaders(init: RequestInit, token: string | null) {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const csrf = csrfToken();
  if (csrf) headers.set("X-CSRFToken", decodeURIComponent(csrf));
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

export async function apiFetch<T>(url: string, init: RequestInit = {}): Promise<T> {
  const protectedRequest = !isAuthEndpoint(url, init.method || "GET");
  const logoutRequest = isLogoutEndpoint(url);
  let token: string | null = null;
  if (protectedRequest && authInitialized && !logoutRequest) token = await ensureAccessToken();
  else if (logoutRequest) token = accessToken;
  const headers = attachRequestHeaders(init, token);
  let authRetried = false;

  while (true) {
    const response = await fetch(url, { ...init, headers, credentials: "same-origin" });
    const body = await response.json().catch(() => ({})) as Record<string, unknown>;
    const parsed = apiErrorSchema.safeParse(body);
    const errorCode = typeof body.error_code === "string" ? body.error_code : "";
    if (
      protectedRequest &&
      !logoutRequest &&
      response.status === 401 &&
      !authRetried &&
      canRetryAfterAuth(init) &&
      ["access_token_expired", "access_token_invalid", "access_token_missing"].includes(errorCode)
    ) {
      authRetried = true;
      token = await refreshAccessToken();
      headers.set("Authorization", `Bearer ${token}`);
      continue;
    }
    if (!response.ok || (parsed.success && parsed.data.success === false)) {
      const message = parsed.success ? parsed.data.error || parsed.data.message : undefined;
      throw new ApiRequestError(
        message || (typeof body.message === "string" ? body.message : `请求失败 (${response.status})`),
        response,
        body,
      );
    }
    return body as T;
  }
}

export async function revokeAllTokens(): Promise<void> {
  await apiFetch<{ success: boolean }>("/accounts/api/tokens/", {
    method: "DELETE",
  });
  clearAccessToken("logged_out");
}
