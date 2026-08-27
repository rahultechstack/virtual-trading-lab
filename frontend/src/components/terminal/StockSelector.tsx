import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { fetchInstruments } from '@/api/instruments';
import {
  ASSET_CLASS_LABELS,
  type AssetClass,
  type AssetFilter,
  type Instrument,
} from '@/types/instruments';

interface Props {
  selected: Instrument | null;
  onSelect: (instrument: Instrument) => void;
}

const FILTERS: ReadonlyArray<{ value: AssetFilter; label: string }> = [
  { value: null, label: 'All' },
  { value: 'STOCK', label: 'Stocks' },
  { value: 'CRYPTO', label: 'Crypto' },
];

/** Order asset classes appear in when nothing is filtered. */
const GROUP_ORDER: AssetClass[] = ['STOCK', 'CRYPTO'];

const GROUP_HEADINGS: Record<AssetClass, string> = {
  STOCK: 'Stocks',
  CRYPTO: 'Cryptocurrency',
};

/**
 * Instrument picker: filter by asset class, search by name or symbol.
 *
 * The universe comes from `GET /instruments` — the backend is the source of
 * truth for what is tradable, and this component never keeps its own list of
 * stocks or coins. The asset filter is applied *server-side* for the same
 * reason: the client should not have to know which symbols are coins.
 *
 * Selecting does not reload the app; the parent swaps the instrument and every
 * panel refetches.
 */
export function StockSelector({ selected, onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<AssetFilter>(null);
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
      fetchInstruments(query, filter, 100, controller.signal)
        .then((rows) => {
          setResults(rows);
          setHighlight(0);
          setError(null);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setError(
            err instanceof Error ? err.message : 'Could not load instruments.',
          );
        })
        .finally(() => setLoading(false));
    }, 180);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, filter, open]);

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
    () =>
      selected
        ? `${selected.symbol} · ${selected.company_name}`
        : 'Select instrument',
    [selected],
  );

  /**
   * Group by asset class, preserving the backend's ranking inside each group.
   * Headings appear only when more than one class is present, so a filtered
   * list is not cluttered with a single redundant header.
   */
  const groups = useMemo(() => {
    const byClass = new Map<AssetClass, Instrument[]>();
    for (const instrument of results) {
      const bucket = byClass.get(instrument.asset_class) ?? [];
      bucket.push(instrument);
      byClass.set(instrument.asset_class, bucket);
    }
    return GROUP_ORDER.filter((assetClass) => byClass.has(assetClass)).map(
      (assetClass) => ({
        assetClass,
        instruments: byClass.get(assetClass) ?? [],
      }),
    );
  }, [results]);

  const showHeadings = groups.length > 1;
  // Flat index across groups, so keyboard highlight matches what is rendered.
  let renderIndex = -1;

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
          {selected?.symbol ?? 'Select instrument'}
        </span>
        <span className="stock-selector__name muted">
          {selected?.company_name ?? 'Search name or symbol'}
        </span>
        {selected && (
          <span
            className={`asset-tag asset-tag--${selected.asset_class.toLowerCase()}`}
          >
            {ASSET_CLASS_LABELS[selected.asset_class]}
          </span>
        )}
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
            placeholder="Search name or symbol…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Search instruments"
          />

          <div className="stock-selector__filters" role="tablist">
            {FILTERS.map(({ value, label: filterLabel }) => (
              <button
                key={filterLabel}
                type="button"
                role="tab"
                aria-selected={filter === value}
                className={`chip ${filter === value ? 'chip--active' : ''}`}
                onClick={() => setFilter(value)}
              >
                {filterLabel}
              </button>
            ))}
          </div>

          {error ? (
            <p className="form-note negative">{error}</p>
          ) : loading && results.length === 0 ? (
            <p className="muted stock-selector__empty">Searching…</p>
          ) : results.length === 0 ? (
            <p className="muted stock-selector__empty">
              No matching instrument.
            </p>
          ) : (
            <ul className="stock-selector__list" role="listbox" aria-label={label}>
              {groups.map(({ assetClass, instruments }) => (
                <li key={assetClass} className="stock-selector__group">
                  {showHeadings && (
                    <p className="stock-selector__group-heading muted">
                      {GROUP_HEADINGS[assetClass]}
                    </p>
                  )}
                  <ul className="stock-selector__group-list">
                    {instruments.map((instrument) => {
                      renderIndex += 1;
                      const index = renderIndex;
                      return (
                        <li key={instrument.symbol}>
                          <button
                            type="button"
                            role="option"
                            aria-selected={instrument.symbol === selected?.symbol}
                            className={`stock-selector__option ${
                              index === highlight
                                ? 'stock-selector__option--active'
                                : ''
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
                            <span
                              className="stock-selector__option-exchange muted"
                              title={instrument.trading_hours}
                            >
                              {instrument.exchange}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
