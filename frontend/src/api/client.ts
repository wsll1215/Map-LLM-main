import { apiErrorSchema } from "../types/api";

function csrfToken() {
  return document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrftoken="))?.split("=")[1] ?? "";
}

export async function apiFetch<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = csrfToken();
  if (token) headers.set("X-CSRFToken", decodeURIComponent(token));
  const response = await fetch(url, { ...init, headers, credentials: "same-origin" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const parsed = apiErrorSchema.safeParse(body);
    throw new Error(parsed.success ? parsed.data.error : `请求失败 (${response.status})`);
  }
  return body as T;
}
