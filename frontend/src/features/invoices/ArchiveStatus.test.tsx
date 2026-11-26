import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '@/api/client';
import { invoicesApi, type Invoice } from '@/api/invoices';
import { renderWithProviders } from '@/test/utils';

import { ArchiveStatus } from './ArchiveStatus';

vi.mock('@/api/invoices', () => ({ invoicesApi: { archive: vi.fn() } }));

const base = { id: 9, status: 'APPROVED', archive_error: null, archive_document_id: null, archive_url: null } as unknown as Invoice;

describe('ArchiveStatus', () => {
  beforeEach(() => {
    vi.spyOn(client, 'refreshAccessToken').mockRejectedValue(new Error('no session'));
  });

  it('links to the filed copy, opening in a new tab', () => {
    renderWithProviders(<ArchiveStatus inv={{ ...base, archive_status: 'ARCHIVED', archive_document_id: 101, archive_url: 'http://localhost:8090/documents/101/details' }} canRetry />);
    const link = screen.getByRole('link', { name: /filed in the document archive/i });
    expect(link).toHaveAttribute('href', 'http://localhost:8090/documents/101/details');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('shows why filing failed and lets an approver try again', async () => {
    vi.mocked(invoicesApi.archive).mockResolvedValue({ ...base, archive_status: 'QUEUED' });
    renderWithProviders(<ArchiveStatus inv={{ ...base, archive_status: 'FAILED', archive_error: 'The document archive could not be reached.' }} canRetry />);
    expect(screen.getByText(/could not be reached/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(invoicesApi.archive).toHaveBeenCalledWith(9);
  });

  it('hides the retry button from people who cannot approve', () => {
    renderWithProviders(<ArchiveStatus inv={{ ...base, archive_status: 'FAILED' }} canRetry={false} />);
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument();
  });

  it('shows nothing when the archive is not used', () => {
    renderWithProviders(<ArchiveStatus inv={{ ...base, archive_status: null }} canRetry />);
    expect(screen.queryByText(/document archive/i)).not.toBeInTheDocument();
  });
});
