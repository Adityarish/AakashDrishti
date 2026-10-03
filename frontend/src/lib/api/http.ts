/** Token-aware fetch helpers for the survey/analysis endpoints (the original client.ts stays untouched). */

import { API_BASE_URL, ApiError } from "./client";

const TOKEN_KEY = "ad_token";

export function getToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session stays in memory only */
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ");
    return JSON.stringify(body);
  } catch {
    return response.statusText || `Request failed with status ${response.status}`;
  }
}

function withAuth(init?: RequestInit): RequestInit {
  const token = getToken();
  if (!token) return init ?? {};
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return { ...init, headers };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, withAuth(init));
  } catch {
    throw new ApiError(`Could not reach the AakashDrishti backend at ${API_BASE_URL}. Is it running?`, 0, true);
  }
  if (!response.ok) throw new ApiError(await parseErrorDetail(response), response.status);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function apiJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** Multipart upload with progress (fetch cannot report upload progress). */
export function apiUpload<T>(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => reject(new ApiError(`Could not reach the AakashDrishti backend at ${API_BASE_URL}. Is it running?`, 0, true));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error body */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else {
        const detail = (body as { detail?: unknown } | null)?.detail;
        reject(new ApiError(typeof detail === "string" ? detail : xhr.statusText || `Upload failed (${xhr.status})`, xhr.status));
      }
    };
    xhr.send(form);
  });
}
