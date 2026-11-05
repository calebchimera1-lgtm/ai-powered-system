import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ConfirmDialog } from './ConfirmDialog';
import { DataTable, Pagination } from './DataTable';

describe('ConfirmDialog', () => {
  it('confirms and cancels', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open title="Deactivate?" message="Are you sure?" confirmLabel="Deactivate" onConfirm={onConfirm} onCancel={onCancel} />,
    );
    expect(screen.getByRole('dialog', { name: 'Deactivate?' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    await userEvent.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('renders nothing when closed', () => {
    render(<ConfirmDialog open={false} title="x" message="y" onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('DataTable', () => {
  const columns = [{ key: 'name', header: 'Name', render: (r: { id: number; name: string }) => r.name }];

  it('renders rows', () => {
    render(<DataTable columns={columns} rows={[{ id: 1, name: 'Sugar 2kg' }]} rowKey={(r) => r.id} />);
    expect(screen.getByRole('cell', { name: 'Sugar 2kg' })).toBeInTheDocument();
  });

  it('shows an empty state', () => {
    render(<DataTable columns={columns} rows={[]} rowKey={(r) => r.id} emptyTitle="No products" />);
    expect(screen.getByText('No products')).toBeInTheDocument();
  });
});

describe('Pagination', () => {
  it('reports range and disables bounds', async () => {
    const onChange = vi.fn();
    render(<Pagination page={1} pages={3} total={45} pageSize={20} onPageChange={onChange} />);
    expect(screen.getByRole('navigation')).toHaveTextContent('1–20 of 45');
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(onChange).toHaveBeenCalledWith(2);
  });
});
