import { z } from 'zod';

// Mirrors the server policy (app/core/security.py: password_problems). The server is the
// final authority; these rules just give instant feedback.
export const newPasswordSchema = z
  .string()
  .min(8, 'Use at least 8 characters')
  .max(128, 'Use at most 128 characters')
  .refine((v) => !/^\d+$/.test(v) && !/^[a-zA-Z]+$/.test(v), 'Mix letters with numbers or symbols');

export const PASSWORD_HINT = 'At least 8 characters, mixing letters with numbers or symbols.';
