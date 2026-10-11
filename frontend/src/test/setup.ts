import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';
import { clearApiCache } from '../lib/useApi';

afterEach(() => {
  cleanup();
  clearApiCache();
  window.location.hash = '';
});
