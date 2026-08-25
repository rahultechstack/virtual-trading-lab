import { NavBar } from '@/components/NavBar';
import { OrderHistoryPage } from '@/components/history/OrderHistoryPage';
import { PerformancePage } from '@/components/history/PerformancePage';
import { PortfolioHistoryPage } from '@/components/history/PortfolioHistoryPage';
import { TradeHistoryPage } from '@/components/history/TradeHistoryPage';
import { Terminal } from '@/components/terminal/Terminal';
import { useHashRoute } from '@/hooks/useHashRoute';

export default function App() {
  const { route, navigate } = useHashRoute();

  return (
    <div className="shell">
      <NavBar route={route} onNavigate={navigate} />

      {route === 'terminal' && <Terminal />}
      {route === 'trades' && <TradeHistoryPage />}
      {route === 'orders' && <OrderHistoryPage />}
      {route === 'portfolio' && <PortfolioHistoryPage />}
      {route === 'performance' && <PerformancePage />}
    </div>
  );
}
