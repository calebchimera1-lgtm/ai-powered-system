import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { lazy, Suspense, type ReactNode } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider } from '@/auth/AuthProvider';
import { RequireAuth, RequirePermission } from '@/auth/ProtectedRoute';
import { PERM } from '@/auth/permissions';
import { AppShell } from '@/components/layout/AppShell';
import { FullPageSpinner } from '@/components/ui/Spinner';
import { ToastProvider } from '@/components/ui/Toast';
import { AccountPage } from '@/features/account/AccountPage';
import { AuditLogPage } from '@/features/audit/AuditLogPage';
import { ChangePasswordPage } from '@/features/auth/ChangePasswordPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage';
import { HomePage } from '@/features/home/HomePage';
import { UsersPage } from '@/features/users/UsersPage';
import { CategoriesPage } from '@/features/categories/CategoriesPage';
import { ExpensesPage } from '@/features/finance/ExpensesPage';
import { PosPage } from '@/features/pos/PosPage';
import { GoodsReceivedDetailPage } from '@/features/purchasing/GoodsReceivedDetailPage';
import { GoodsReceivedPage } from '@/features/purchasing/GoodsReceivedPage';
import { PurchaseOrderDetailPage } from '@/features/purchasing/PurchaseOrderDetailPage';
import { PurchaseOrderFormPage } from '@/features/purchasing/PurchaseOrderFormPage';
import { PurchaseOrdersPage } from '@/features/purchasing/PurchaseOrdersPage';
import { ReceiveGoodsPage } from '@/features/purchasing/ReceiveGoodsPage';
import { ReturnsPage } from '@/features/sales/ReturnsPage';
import { SaleDetailPage } from '@/features/sales/SaleDetailPage';
import { SalesPage } from '@/features/sales/SalesPage';
import { ProductDetailPage } from '@/features/products/ProductDetailPage';
import { ProductsPage } from '@/features/products/ProductsPage';
import { AdjustmentsPage } from '@/features/stock/AdjustmentsPage';
import { StockMovementsPage } from '@/features/stock/StockMovementsPage';
import { SupplierDetailPage } from '@/features/suppliers/SupplierDetailPage';
import { SuppliersPage } from '@/features/suppliers/SuppliersPage';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Don't retry client errors (403, 404, 422); retry network/server errors once.
        retry: (count, error) =>
          count < 1 && !(isAxiosError(error) && (error.response?.status ?? 500) < 500),
      },
    },
  });
}

// The profit page carries the charting library; load it only when opened.
const FinancePage = lazy(() =>
  import('@/features/finance/FinancePage').then((m) => ({ default: m.FinancePage })),
);

function Guard({ perms, children }: { perms: string[]; children: ReactNode }) {
  return <RequirePermission anyOf={perms}>{children}</RequirePermission>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/change-password" element={<ChangePasswordPage />} />
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="/pos" element={<Guard perms={[PERM.SALES_CREATE]}><PosPage /></Guard>} />
          <Route path="/sales" element={<Guard perms={[PERM.SALES_READ_OWN, PERM.SALES_READ_ALL]}><SalesPage /></Guard>} />
          <Route path="/sales/:id" element={<Guard perms={[PERM.SALES_READ_OWN, PERM.SALES_READ_ALL]}><SaleDetailPage /></Guard>} />
          <Route path="/returns" element={<Guard perms={[PERM.RETURNS_REQUEST, PERM.RETURNS_APPROVE]}><ReturnsPage /></Guard>} />
          <Route path="/purchasing/orders" element={<Guard perms={[PERM.PURCHASES_READ]}><PurchaseOrdersPage /></Guard>} />
          <Route path="/purchasing/orders/new" element={<Guard perms={[PERM.PURCHASES_WRITE]}><PurchaseOrderFormPage /></Guard>} />
          <Route path="/purchasing/orders/:id" element={<Guard perms={[PERM.PURCHASES_READ]}><PurchaseOrderDetailPage /></Guard>} />
          <Route path="/purchasing/orders/:id/edit" element={<Guard perms={[PERM.PURCHASES_WRITE]}><PurchaseOrderFormPage /></Guard>} />
          <Route path="/purchasing/receive" element={<Guard perms={[PERM.PURCHASES_WRITE]}><ReceiveGoodsPage /></Guard>} />
          <Route path="/purchasing/receipts" element={<Guard perms={[PERM.PURCHASES_READ]}><GoodsReceivedPage /></Guard>} />
          <Route path="/purchasing/receipts/:id" element={<Guard perms={[PERM.PURCHASES_READ]}><GoodsReceivedDetailPage /></Guard>} />
          <Route path="/finance" element={<Guard perms={[PERM.FINANCE_READ]}><Suspense fallback={<FullPageSpinner label="Loading…" />}><FinancePage /></Suspense></Guard>} />
          <Route path="/expenses" element={<Guard perms={[PERM.FINANCE_READ]}><ExpensesPage /></Guard>} />
          <Route path="/products" element={<Guard perms={[PERM.PRODUCTS_READ]}><ProductsPage /></Guard>} />
          <Route path="/products/:id" element={<Guard perms={[PERM.PRODUCTS_READ]}><ProductDetailPage /></Guard>} />
          <Route path="/categories" element={<Guard perms={[PERM.PRODUCTS_WRITE]}><CategoriesPage /></Guard>} />
          <Route path="/stock/movements" element={<Guard perms={[PERM.STOCK_READ]}><StockMovementsPage /></Guard>} />
          <Route path="/stock/adjustments" element={<Guard perms={[PERM.STOCK_READ]}><AdjustmentsPage /></Guard>} />
          <Route path="/suppliers" element={<Guard perms={[PERM.SUPPLIERS_READ]}><SuppliersPage /></Guard>} />
          <Route path="/suppliers/:id" element={<Guard perms={[PERM.SUPPLIERS_READ]}><SupplierDetailPage /></Guard>} />
          <Route
            path="/users"
            element={
              <RequirePermission anyOf={[PERM.USERS_READ]}>
                <UsersPage />
              </RequirePermission>
            }
          />
          <Route
            path="/audit-log"
            element={
              <RequirePermission anyOf={[PERM.AUDIT_READ]}>
                <AuditLogPage />
              </RequirePermission>
            }
          />
          <Route path="/account" element={<AccountPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}

const queryClient = createQueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
