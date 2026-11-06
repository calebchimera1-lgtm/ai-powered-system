import { isAxiosError } from 'axios';

import type { ApiErrorBody } from '@/api/types';

export interface ParsedError {
  code: string;
  message: string;
  fieldErrors: Record<string, string>;
}

/** Turn any thrown value into a user-friendly message plus per-field errors. */
export function parseError(error: unknown): ParsedError {
  if (isAxiosError<ApiErrorBody>(error)) {
    if (!error.response) {
      return {
        code: 'NETWORK_ERROR',
        message: 'Cannot reach the server. Check your connection and try again.',
        fieldErrors: {},
      };
    }
    const body = error.response.data?.error;
    if (body) {
      const fieldErrors: Record<string, string> = {};
      // `details` is usually a list of field errors, but some errors carry an object
      // (e.g. the existing record for a duplicate invoice); only lists map to fields.
      if (Array.isArray(body.details)) {
        for (const d of body.details) {
          if (d && d.field && !fieldErrors[d.field]) fieldErrors[d.field] = d.message;
        }
      }
      return { code: body.code, message: body.message, fieldErrors };
    }
    return {
      code: `HTTP_${error.response.status}`,
      message: `The server returned an error (${error.response.status}).`,
      fieldErrors: {},
    };
  }
  if (error instanceof Error) return { code: 'ERROR', message: error.message, fieldErrors: {} };
  return { code: 'ERROR', message: 'Something went wrong.', fieldErrors: {} };
}

export function errorMessage(error: unknown): string {
  return parseError(error).message;
}
