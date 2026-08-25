import { NAV, type Route } from '@/hooks/useHashRoute';

interface Props {
  route: Route;
  onNavigate: (hash: string) => void;
}

/** Top navigation. Anchors, so middle-click and back/forward work. */
export function NavBar({ route, onNavigate }: Props) {
  return (
    <nav className="navbar">
      <span className="navbar__brand">
        Virtual Trading
        <span className="muted navbar__tag">paper</span>
      </span>

      <div className="navbar__links">
        {NAV.map((entry) => (
          <a
            key={entry.route}
            href={entry.hash}
            className={`navlink ${route === entry.route ? 'navlink--active' : ''}`}
            onClick={(event) => {
              event.preventDefault();
              onNavigate(entry.hash);
            }}
            aria-current={route === entry.route ? 'page' : undefined}
          >
            {entry.label}
          </a>
        ))}
      </div>
    </nav>
  );
}
