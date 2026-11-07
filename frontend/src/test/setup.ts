import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});

// jsdom has no layout engine; pages may scroll to the top after an action.
window.scrollTo = (() => {}) as typeof window.scrollTo;
