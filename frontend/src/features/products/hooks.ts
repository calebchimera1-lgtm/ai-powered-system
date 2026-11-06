import { useQuery } from '@tanstack/react-query';

import { categoriesApi, suppliersApi } from '@/api/catalog';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';

export function useCategories(includeInactive = false) {
  return useQuery({
    queryKey: ['categories', { includeInactive }],
    queryFn: () => categoriesApi.list(includeInactive),
    staleTime: 60_000,
  });
}

/** Active suppliers for dropdowns (only fetched for roles that may see suppliers). */
export function useSupplierOptions() {
  const { can } = useAuth();
  return useQuery({
    queryKey: ['suppliers', 'options'],
    queryFn: () => suppliersApi.list({ is_active: true, page_size: 100 }),
    enabled: can(PERM.SUPPLIERS_READ),
    staleTime: 60_000,
    select: (page) => page.items,
  });
}
