/** Thin fetch wrapper for the AakashDrishti backend. No UI concerns here. */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  /** True when the request never reached the server (network error / endpoint not deployed yet). */
  isNetworkError: boolean;

  constructor(message: string, status: number, isNetworkError = false) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.isNetworkError = isNetworkError;
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    return JSON.stringify(body);
  } catch {
    return response.statusText || `Request failed with status ${response.status}`;
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      `Could not reach the AakashDrishti backend at ${API_BASE_URL}${path}. Is it running?`,
      0,
      true,
    );
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export { API_BASE_URL };
