import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import { FolderPlus, Pencil, Power, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link } from 'react-router-dom';
import { z } from 'zod';

import { categoriesApi } from '@/api/catalog';
import type { Category } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { ActionMenu } from '@/components/ui/ActionMenu';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { DataTable } from '@/components/ui/DataTable';
import { Input, Select, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { useCategories } from '@/features/products/hooks';
import { errorMessage, parseError } from '@/lib/errors';

const schema = z.object({
  name: z.string().trim().min(2, 'Enter a name').max(100),
  parent_id: z.string().optional(),
  description: z.string().max(500).optional(),
});
type FormValues = z.infer<typeof schema>;

export function CategoriesPage() {
  const { can } = useAuth();
  const canWrite = can(PERM.PRODUCTS_WRITE);
  const toast = useToast();
  const qc = useQueryClient();
  const list = useCategories(true);
  const [editing, setEditing] = useState<Category | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Category | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const { register, handleSubmit, reset, setError, formState: { errors, isSubmitting } } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const editingKey = editing === 'new' ? 'new' : editing?.id ?? null;
  const latestEditing = useRef(editing);
  latestEditing.current = editing;
  useEffect(() => {
    const editing = latestEditing.current;
    if (editing) {
      setFormError(null);
      reset(editing === 'new'
        ? { name: '', parent_id: '', description: '' }
        : { name: editing.name, parent_id: editing.parent_id ? String(editing.parent_id) : '', description: editing.description ?? '' });
    }
  }, [editingKey, reset]);

  const refresh = () => qc.invalidateQueries({ queryKey: ['categories'] });

  const save = async (v: FormValues) => {
    setFormError(null);
    const body = { name: v.name, parent_id: v.parent_id ? Number(v.parent_id) : null, description: v.description?.trim() || null };
    try {
      if (editing === 'new') await categoriesApi.create(body);
      else if (editing) await categoriesApi.update(editing.id, body);
      toast.success('Category saved');
      setEditing(null);
      refresh();
    } catch (err) {
      const parsed = parseError(err);
      if (parsed.fieldErrors.name) setError('name', { message: parsed.message });
      else setFormError(parsed.message);
    }
  };

  const toggle = async (c: Category) => {
    try {
      await categoriesApi.update(c.id, { is_active: !c.is_active });
      toast.success(c.is_active ? 'Category hidden' : 'Category active again');
      refresh();
    } catch (err) {
      toast.error('Could not update', errorMessage(err));
    }
  };

  const parentOptions = (list.data ?? []).filter((c) => c.is_active && (editing === 'new' || !editing || (c.id !== editing.id && !c.path.startsWith(`${editing.path} ›`))));

  return (
    <>
      <PageHeader title="Categories" description="Group products for searching and reports."
        actions={canWrite && <Button icon={<FolderPlus className="h-4 w-4" />} onClick={() => setEditing('new')}>Add category</Button>} />
      <Card bodyClassName="p-0">
        {list.isError && <div className="p-4"><Alert tone="error">{errorMessage(list.error)}</Alert></div>}
        <DataTable
          caption="Categories"
          columns={[
            { key: 'path', header: 'Category', render: (c) => (
              <div style={{ paddingLeft: `${(c.path.split('›').length - 1) * 1.25}rem` }}>
                <Link to={`/products?category=${c.id}`} className="font-medium text-gray-900 hover:text-brand-700">{c.name}</Link>
                {c.description && <p className="text-xs text-gray-500">{c.description}</p>}
              </div>
            ) },
            { key: 'count', header: 'Active products', className: 'text-right', render: (c) => <span className="tabular-nums">{c.product_count}</span> },
            { key: 'status', header: 'Status', render: (c) => c.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Hidden</Badge> },
            { key: 'actions', header: <span className="sr-only">Actions</span>, className: 'w-12 text-right', render: (c) => canWrite ? (
              <ActionMenu label={`Actions for ${c.name}`} items={[
                { label: 'Edit', icon: <Pencil className="h-4 w-4" />, onClick: () => setEditing(c) },
                { label: c.is_active ? 'Hide' : 'Show again', icon: <Power className="h-4 w-4" />, onClick: () => toggle(c) },
                { label: 'Delete', icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setDeleting(c) },
              ]} />
            ) : null },
          ]}
          rows={list.data ?? []}
          rowKey={(c) => c.id}
          loading={list.isLoading}
          emptyTitle="No categories yet"
        />
      </Card>

      <Modal open={Boolean(editing)} onClose={() => setEditing(null)} busy={isSubmitting} size="sm"
        title={editing === 'new' ? 'Add category' : 'Edit category'}
        footer={<>
          <Button variant="secondary" onClick={() => setEditing(null)} disabled={isSubmitting}>Cancel</Button>
          <Button type="submit" form="category-form" loading={isSubmitting}>Save</Button>
        </>}>
        <form id="category-form" onSubmit={handleSubmit(save)} className="space-y-4" noValidate>
          {formError && <Alert tone="error">{formError}</Alert>}
          <Input label="Name" required error={errors.name?.message} {...register('name')} />
          <Select label="Inside" placeholder="Top level" options={parentOptions.map((c) => ({ value: String(c.id), label: c.path }))} {...register('parent_id')} />
          <Textarea label="Description" rows={2} {...register('description')} />
        </form>
      </Modal>

      <ConfirmDialog open={Boolean(deleting)} title="Delete this category?"
        message={`${deleting?.name} can only be deleted if it has no products and no sub-categories.`}
        confirmLabel="Delete"
        onCancel={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await categoriesApi.remove(deleting.id);
            toast.success('Category deleted');
            refresh();
          } catch (err) {
            toast.error('Cannot delete', errorMessage(err));
          }
          setDeleting(null);
        }} />
    </>
  );
}
