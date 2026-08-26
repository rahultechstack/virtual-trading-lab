import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';
import { INSTRUMENT } from '@/config/instrument';
import './styles/global.css';
import './styles/terminal.css';

// One place defines the instrument; the tab title follows it.
document.title = `Virtual Trading Platform — ${INSTRUMENT.displayName}`;

const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element #root not found in index.html');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
