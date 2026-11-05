import { describe, expect, it } from 'vitest';

import { describeUserAgent, formatDateTime, formatKES } from './format';

describe('formatKES', () => {
  it('formats Kenyan Shillings with two decimals and grouping', () => {
    expect(formatKES(1250)).toMatch(/^Ksh\s?1,250\.00$|^KES\s?1,250\.00$/);
    expect(formatKES('99.5')).toMatch(/99\.50$/);
  });
  it('shows a dash for missing or invalid values', () => {
    expect(formatKES(null)).toBe('—');
    expect(formatKES('abc')).toBe('—');
  });
});

describe('formatDateTime', () => {
  it('renders in Nairobi time (UTC+3)', () => {
    expect(formatDateTime('2026-01-15T21:30:00Z')).toContain('16 Jan 2026');
  });
  it('handles empty input', () => {
    expect(formatDateTime(null)).toBe('—');
  });
});

describe('describeUserAgent', () => {
  it('recognises common browsers', () => {
    expect(
      describeUserAgent(
        'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36',
      ),
    ).toBe('Chrome on Android');
    expect(describeUserAgent(null)).toBe('Unknown device');
  });
});
