import clsx from 'clsx';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';

import { EmptyState } from './EmptyState';
import { Spinner } from './Spinner';

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  className?: string;
  /** Hide on small screens to keep tables readable on phones. */
  hideOnMobile?: boolean;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  caption?: string;
}

/** Responsive table: scrolls horizontally inside its card, never the whole page. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  emptyTitle = 'Nothing to show',
  emptyDescription,
  caption,
}: DataTableProps<T>) {
  return (
    <div className="relative">
      <div className="relative overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="bg-gray-50">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={clsx(
                    'whitespace-nowrap px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500',
                    c.hideOnMobile && 'hidden md:table-cell',
                    c.className,
                  )}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {rows.map((row) => (
              <tr key={rowKey(row)} className="hover:bg-gray-50/70">
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={clsx(
                      'px-4 py-3 align-middle text-gray-700',
                      c.hideOnMobile && 'hidden md:table-cell',
                      c.className,
                    )}
                  >
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {loading && rows.length === 0 && (
        <div className="flex justify-center py-12">
          <Spinner label="Loading…" />
        </div>
      )}
      {!loading && rows.length === 0 && (
        <EmptyState title={emptyTitle} description={emptyDescription} />
      )}
      {loading && rows.length > 0 && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/60">
          <Spinner />
        </div>
      )}
    </div>
  );
}

export function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPageChange,
}: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between gap-3 border-t border-gray-100 px-4 py-3 text-sm text-gray-600"
    >
      <p>
        <span className="font-medium text-gray-900">{from}</span>–
        <span className="font-medium text-gray-900">{to}</span> of{' '}
        <span className="font-medium text-gray-900">{total}</span>
      </p>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="rounded-lg border border-gray-300 p-2.5 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 sm:p-1.5"
          aria-label="Previous page"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="px-2">
          Page {page} of {pages}
        </span>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pages}
          className="rounded-lg border border-gray-300 p-2.5 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 sm:p-1.5"
          aria-label="Next page"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </nav>
  );
}
