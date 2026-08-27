/**
 * Thin HTTP transport shared by every endpoint module.
 * Components never call `fetch` directly - they go through `api/*` functions.
 *
 * Where the backend lives is NOT decided here. It comes from
 * `@/config/api`, which is the one place to change it.
 */

import { API_BASE_URL, apiUrl, wsUrl } from '@/config/api';

export { apiUrl, wsUrl };

/** The error envelope the backend returns for domain failures. */
interface ErrorEnvelope {
  error?: { code?: string; message?: string };
  detail?: unknown;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    /** Machine-readable code, e.g. `insufficient_funds`. */
    readonly code?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

/** Turn a non-2xx response into an ApiError, unwrapping the error envelope. */
async function toApiError(response: Response, path: string): Promise<ApiError> {
  let body: ErrorEnvelope | null = null;
  try {
    body = (await response.json()) as ErrorEnvelope;
  } catch {
    // Not JSON; fall through to the generic message.
  }

  const message =
    body?.error?.message ??
    (typeof body?.detail === 'string' ? body.detail : undefined) ??
    `Request to ${path} failed with HTTP ${response.status}.`;

  return new ApiError(message, response.status, body?.error?.code);
}

async function request<T>(
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;

  try {
    response = await fetch(apiUrl(path), {
      ...init,
      headers: { Accept: 'application/json', ...(init.headers ?? {}) },
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    // Network-level failure: backend down, wrong port, CORS rejection.
    throw new ApiError(
      `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`,
    );
  }

  if (!response.ok) {
    throw await toApiError(response, path);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: 'GET' }, signal);
}

export function apiPost<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return request<T>(
    path,
    {
      method: 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    signal,
  );
}
