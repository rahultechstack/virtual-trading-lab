import { apiGet, apiPost } from './client';
import type { Wallet } from '@/types/trading';

export function fetchWallet(signal?: AbortSignal): Promise<Wallet> {
  return apiGet<Wallet>('/wallet', signal);
}

export function initializeWallet(initialBalance?: string): Promise<Wallet> {
  return apiPost<Wallet>(
    '/wallet/initialize',
    initialBalance ? { initial_balance: initialBalance } : undefined,
  );
}

export function resetWallet(initialBalance?: string): Promise<Wallet> {
  return apiPost<Wallet>(
    '/wallet/reset',
    initialBalance ? { initial_balance: initialBalance } : undefined,
  );
}
