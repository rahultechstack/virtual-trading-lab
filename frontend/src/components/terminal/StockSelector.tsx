import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { fetchInstruments } from '@/api/instruments';
import type { Instrument } from '@/types/instruments';

interface Props {
  selected: Instrument | null;
  onSelect: (instrument: Instrument) => void;
}

/**
 * Stock picker: search by company name or NSE symbol, pick from the list.
 *
 * The universe comes from `GET /instruments` — the backend is the source of
 * truth for what is tradable, and this component never keeps its own list.
 * Selecting does not reload the app; the parent swaps the symbol and every
 * panel refetches.
 */
export function StockSelector({ selected, onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Instrument[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState(0);

  const rootRef = useRef<HTMLDivElement | null>(null);

  // Debounced search, so typing does not fire a request per keystroke.
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      fetchInstruments(query, 50, controller.signal)
        .then((rows) => {
          setResults(rows);
          setHighlight(0);
          setError(null);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setError(err instanceof Error ? err.message : 'Could not load stocks.');
        })
        .finally(() => setLoading(false));
    }, 180);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, open]);

  // Close when clicking elsewhere.
  useEffect(() => {
    if (!open) return;
    const onDocumentClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocumentClick);
    return () => document.removeEventListener('mousedown', onDocumentClick);
  }, [open]);

  const choose = useCallback(
    (instrument: Instrument) => {
      onSelect(instrument);
      setOpen(false);
      setQuery('');
    },
    [onSelect],
  );

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!open) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlight((index) => Math.min(index + 1, results.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlight((index) => Math.max(index - 1, 0));
    } else if (event.key === 'Enter' && results[highlight]) {
      event.preventDefault();
      choose(results[highlight]);
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  };

  const label = useMemo(
    () => (selected ? `${selected.symbol} · ${selected.company_name}` : 'Select stock'),
    [selected],
  );

  return (
    <div className="stock-selector" ref={rootRef}>
      <button
        type="button"
        className="stock-selector__current"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="stock-selector__symbol">
          {selected?.symbol ?? 'Select stock'}
        </span>
        <span className="stock-selector__name muted">
          {selected?.company_name ?? 'Search company or symbol'}
        </span>
        <span className="stock-selector__exchange muted">
          {selected?.exchange ?? 'NSE'}
        </span>
        <i className="stock-selector__caret" aria-hidden="true" />
      </button>

      {open && (
        <div className="stock-selector__popover">
          <input
            className="field__input stock-selector__search"
            type="search"
            autoFocus
            placeholder="Search company or symbol…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Search stocks"
          />

          {error ? (
            <p className="form-note negative">{error}</p>
          ) : loading && results.length === 0 ? (
            <p className="muted stock-selector__empty">Searching…</p>
          ) : results.length === 0 ? (
            <p className="muted stock-selector__empty">No matching stock.</p>
          ) : (
            <ul className="stock-selector__list" role="listbox" aria-label={label}>
              {results.map((instrument, index) => (
                <li key={instrument.symbol}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={instrument.symbol === selected?.symbol}
                    className={`stock-selector__option ${
                      index === highlight ? 'stock-selector__option--active' : ''
                    } ${
                      instrument.symbol === selected?.symbol
                        ? 'stock-selector__option--selected'
                        : ''
                    }`}
                    onMouseEnter={() => setHighlight(index)}
                    onClick={() => choose(instrument)}
                  >
                    <span className="stock-selector__option-symbol">
                      {instrument.symbol}
                    </span>
                    <span className="stock-selector__option-name muted">
                      {instrument.company_name}
                    </span>
                    <span className="stock-selector__option-exchange muted">
                      {instrument.exchange}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
