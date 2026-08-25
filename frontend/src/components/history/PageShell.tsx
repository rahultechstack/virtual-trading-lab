import type { ReactNode } from 'react';

interface Props {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  children: ReactNode;
}

/** Shared frame for the history pages: title, state handling, content. */
export function PageShell({
  title,
  subtitle,
  actions,
  loading = false,
  error = null,
  onRetry,
  children,
}: Props) {
  return (
    <section className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{title}</h1>
          {subtitle && <p className="muted page__subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="page__actions">{actions}</div>}
      </header>

      {error ? (
        <div className="alert">
          <strong>Could not load this page.</strong>
          <p>{error}</p>
          {onRetry && (
            <button type="button" className="chip" onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      ) : loading ? (
        <p className="muted">Loading\u2026</p>
      ) : (
        children
      )}
    </section>
  );
}
