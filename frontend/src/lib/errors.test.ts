import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it } from 'vitest';

import { parseError } from './errors';

function axiosError(status: number | null, data?: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() };
  const response =
    status === null
      ? undefined
      : { status, statusText: '', headers: {}, config, data };
  return new AxiosError('fail', 'ERR', config, null, response as never);
}

describe('parseError', () => {
  it('reads the API error envelope with field details', () => {
    const err = axiosError(409, {
      error: { code: 'CONFLICT', message: 'That username is already taken', details: [{ field: 'username', message: 'already taken' }] },
    });
    expect(parseError(err)).toEqual({
      code: 'CONFLICT',
      message: 'That username is already taken',
      fieldErrors: { username: 'already taken' },
    });
  });
  it('keeps the message when details is an object, not a list', () => {
    const err = axiosError(409, {
      error: { code: 'DUPLICATE_INVOICE', message: 'Invoice INV-5 was already received', details: { purchase_id: 3 } },
    });
    expect(parseError(err)).toEqual({ code: 'DUPLICATE_INVOICE', message: 'Invoice INV-5 was already received', fieldErrors: {} });
  });

  it('explains network failures', () => {
    expect(parseError(axiosError(null)).code).toBe('NETWORK_ERROR');
  });
  it('falls back for unexpected bodies', () => {
    expect(parseError(axiosError(502, '<html>')).message).toContain('502');
  });
});
