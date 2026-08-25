import { useCallback, useEffect, useState } from 'react';

export type Route =
  | 'terminal'
  | 'trades'
  | 'orders'
  | 'portfolio'
  | 'performance';

const ROUTES: Record<string, Route> = {
  '': 'terminal',
  '#/': 'terminal',
  '#/trades': 'trades',
  '#/orders': 'orders',
  '#/portfolio': 'portfolio',
  '#/performance': 'performance',
};

export const NAV: ReadonlyArray<{ route: Route; hash: string; label: string }> = [
  { route: 'terminal', hash: '#/', label: 'Terminal' },
  { route: 'trades', hash: '#/trades', label: 'Trade History' },
  { route: 'orders', hash: '#/orders', label: 'Order History' },
  { route: 'portfolio', hash: '#/portfolio', label: 'Portfolio History' },
  { route: 'performance', hash: '#/performance', label: 'Performance' },
];

function currentRoute(): Route {
  return ROUTES[window.location.hash] ?? 'terminal';
}

/**
 * Minimal hash-based routing.
 *
 * Hash routing rather than a router library: it gives real URLs and working
 * back/forward for five static pages without adding a dependency, and needs
 * no server-side rewrite rules.
 */
export function useHashRoute(): { route: Route; navigate: (hash: string) => void } {
  const [route, setRoute] = useState<Route>(currentRoute);

  useEffect(() => {
    const onChange = () => setRoute(currentRoute());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  const navigate = useCallback((hash: string) => {
    window.location.hash = hash;
  }, []);

  return { route, navigate };
}
