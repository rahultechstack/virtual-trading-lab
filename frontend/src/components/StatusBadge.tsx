import type { ServiceStatus } from '@/types/health';

interface Props {
  status: ServiceStatus;
}

const LABELS: Record<ServiceStatus, string> = {
  ok: 'OK',
  degraded: 'DEGRADED',
  error: 'ERROR',
};

export function StatusBadge({ status }: Props) {
  return <span className={`badge badge--${status}`}>{LABELS[status]}</span>;
}
