/**
 * Mirrors `backend/app/schemas/health.py`. Keep both in sync.
 */

export type ServiceStatus = 'ok' | 'degraded' | 'error';

export interface DatabaseHealth {
  status: ServiceStatus;
  detail: string;
  latency_ms: number | null;
}

export interface HealthResponse {
  status: ServiceStatus;
  app_name: string;
  version: string;
  environment: string;
  timestamp: string;
  database: DatabaseHealth;
}
