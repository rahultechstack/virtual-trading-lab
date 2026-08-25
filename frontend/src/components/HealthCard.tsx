import { StatusBadge } from './StatusBadge';
import { useHealth } from '@/hooks/useHealth';

/**
 * Stage 1 proof of connectivity: browser -> FastAPI -> PostgreSQL.
 */
export function HealthCard() {
  const { state, data, error, refresh } = useHealth();

  return (
    <section className="card">
      <header className="card__header">
        <h2>Backend connection</h2>
        <button type="button" onClick={refresh} disabled={state === 'loading'}>
          {state === 'loading' ? 'Checking…' : 'Re-check'}
        </button>
      </header>

      {state === 'loading' && <p className="muted">Contacting FastAPI…</p>}

      {state === 'error' && (
        <div className="alert">
          <strong>Could not reach the backend.</strong>
          <p>{error}</p>
          <p className="muted">
            Start it with <code>uvicorn app.main:app --reload</code> from the
            <code> backend/</code> directory.
          </p>
        </div>
      )}

      {state === 'success' && data && (
        <dl className="kv">
          <dt>API</dt>
          <dd>
            <StatusBadge status={data.status} />
          </dd>

          <dt>Service</dt>
          <dd>
            {data.app_name} <span className="muted">v{data.version}</span>
          </dd>

          <dt>Environment</dt>
          <dd>{data.environment}</dd>

          <dt>PostgreSQL</dt>
          <dd>
            <StatusBadge status={data.database.status} />
            {data.database.latency_ms !== null && (
              <span className="muted"> {data.database.latency_ms} ms</span>
            )}
          </dd>

          <dt>Detail</dt>
          <dd className="muted">{data.database.detail}</dd>

          <dt>Server time</dt>
          <dd className="muted">{new Date(data.timestamp).toLocaleString()}</dd>
        </dl>
      )}
    </section>
  );
}
