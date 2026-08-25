import { HealthCard } from '@/components/HealthCard';

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <h1>Virtual Trading Platform</h1>
        <p className="muted">
          Paper trading · NSE:RELIANCE · single virtual wallet
        </p>
      </header>

      <main className="app__main">
        <HealthCard />

        <section className="card card--muted">
          <h2>Stage 1 — foundation</h2>
          <p className="muted">
            Project scaffolding only. Trading, market data, charts, indicators
            and backtesting are not implemented yet.
          </p>
        </section>
      </main>
    </div>
  );
}
