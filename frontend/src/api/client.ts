/**
 * Thin HTTP transport shared by every endpoint module.
 * Components never call `fetch` directly — they go through `api/*` functions.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const V1_PREFIX = import.meta.env.VITE_API_V1_PREFIX ?? '/api/v1';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function apiUrl(path: string): string {
  return `${BASE_URL}${V1_PREFIX}${path}`;
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;

  try {
    response = await fetch(apiUrl(path), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
  } catch {
    // Network-level failure: backend down, wrong port, CORS rejection.
    throw new ApiError(
      `Cannot reach the API at ${BASE_URL}. Is the backend running?`,
    );
  }

  if (!response.ok) {
    throw new ApiError(
      `Request to ${path} failed with HTTP ${response.status}.`,
      response.status,
    );
  }

  return (await response.json()) as T;
}
