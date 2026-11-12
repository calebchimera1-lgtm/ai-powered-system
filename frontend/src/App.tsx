import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { lazy, type ComponentType, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { AuthProvider } from '@/auth/AuthProvider';
import { RequireAuth, RequirePermission } from '@/auth/ProtectedRoute';
import { PERM } from '@/auth/permissions';
import { AppShell } from '@/components/layout/AppShell';
import { ToastProvider } from '@/components/ui/Toast';
import { ChangePasswordPage } from '@/features/auth/ChangePasswordPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage';
import { NotFoundPage } from '@/features/errors/NotFoundPage';

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

// Every page inside the app shell is its own chunk, so a cashier's first load doesn't carry
// the charting library, the invoice reviewer or the admin screens. The shell's <Suspense>
// shows a spinner while a page's chunk downloads.
function page<K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) {
  return lazy(() => load().then((m) => ({ default: m[name] })));
}
const FinancePage = page(() => import('@/features/finance/FinancePage'), 'FinancePage');
const AccountPage = page(() => import('@/features/account/AccountPage'), 'AccountPage');
const AuditLogPage = page(() => import('@/features/audit/AuditLogPage'), 'AuditLogPage');
const HomePage = page(() => import('@/features/home/HomePage'), 'HomePage');
const UsersPage = page(() => import('@/features/users/UsersPage'), 'UsersPage');
const CategoriesPage = page(() => import('@/features/categories/CategoriesPage'), 'CategoriesPage');
const ExpensesPage = page(() => import('@/features/finance/ExpensesPage'), 'ExpensesPage');
const PosPage = page(() => import('@/features/pos/PosPage'), 'PosPage');
const AnomaliesPage = page(() => import('@/features/anomalies/AnomaliesPage'), 'AnomaliesPage');
const AnomalyDetailPage = page(() => import('@/features/anomalies/AnomalyDetailPage'), 'AnomalyDetailPage');
const ForecastDetailPage = page(() => import('@/features/forecasting/ForecastDetailPage'), 'ForecastDetailPage');
const ForecastsPage = page(() => import('@/features/forecasting/ForecastsPage'), 'ForecastsPage');
const ReorderPage = page(() => import('@/features/forecasting/ReorderPage'), 'ReorderPage');
const BackupsPage = page(() => import('@/features/admin/BackupsPage'), 'BackupsPage');
const ReportsPage = page(() => import('@/features/reports/ReportsPage'), 'ReportsPage');
const NotificationsPage = page(() => import('@/features/notifications/NotificationsPage'), 'NotificationsPage');
const InvoiceReviewPage = page(() => import('@/features/invoices/InvoiceReviewPage'), 'InvoiceReviewPage');
const InvoicesPage = page(() => import('@/features/invoices/InvoicesPage'), 'InvoicesPage');
const GoodsReceivedDetailPage = page(() => import('@/features/purchasing/GoodsReceivedDetailPage'), 'GoodsReceivedDetailPage');
const GoodsReceivedPage = page(() => import('@/features/purchasing/GoodsReceivedPage'), 'GoodsReceivedPage');
const PurchaseOrderDetailPage = page(() => import('@/features/purchasing/PurchaseOrderDetailPage'), 'PurchaseOrderDetailPage');
const PurchaseOrderFormPage = page(() => import('@/features/purchasing/PurchaseOrderFormPage'), 'PurchaseOrderFormPage');
const PurchaseOrdersPage = page(() => import('@/features/purchasing/PurchaseOrdersPage'), 'PurchaseOrdersPage');
const ReceiveGoodsPage = page(() => import('@/features/purchasing/ReceiveGoodsPage'), 'ReceiveGoodsPage');
const ReturnsPage = page(() => import('@/features/sales/ReturnsPage'), 'ReturnsPage');
const SaleDetailPage = page(() => import('@/features/sales/SaleDetailPage'), 'SaleDetailPage');
const SalesPage = page(() => import('@/features/sales/SalesPage'), 'SalesPage');
const ProductDetailPage = page(() => import('@/features/products/ProductDetailPage'), 'ProductDetailPage');
const ProductsPage = page(() => import('@/features/products/ProductsPage'), 'ProductsPage');
const AdjustmentsPage = page(() => import('@/features/stock/AdjustmentsPage'), 'AdjustmentsPage');
const StockMovementsPage = page(() => import('@/features/stock/StockMovementsPage'), 'StockMovementsPage');
const SupplierDetailPage = page(() => import('@/features/suppliers/SupplierDetailPage'), 'SupplierDetailPage');
const SuppliersPage = page(() => import('@/features/suppliers/SuppliersPage'), 'SuppliersPage');

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
          <Route path="/purchasing/invoices" element={<Guard perms={[PERM.INVOICES_UPLOAD, PERM.INVOICES_APPROVE]}><InvoicesPage /></Guard>} />
          <Route path="/purchasing/invoices/:id" element={<Guard perms={[PERM.INVOICES_UPLOAD, PERM.INVOICES_APPROVE]}><InvoiceReviewPage /></Guard>} />
          <Route path="/forecasts" element={<Guard perms={[PERM.FORECASTS_READ]}><ForecastsPage /></Guard>} />
          <Route path="/forecasts/:productId" element={<Guard perms={[PERM.FORECASTS_READ]}><ForecastDetailPage /></Guard>} />
          <Route path="/reorder" element={<Guard perms={[PERM.PURCHASES_WRITE]}><ReorderPage /></Guard>} />
          <Route path="/anomalies" element={<Guard perms={[PERM.ANOMALIES_READ]}><AnomaliesPage /></Guard>} />
          <Route path="/anomalies/:id" element={<Guard perms={[PERM.ANOMALIES_READ]}><AnomalyDetailPage /></Guard>} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/admin/backups" element={<Guard perms={[PERM.BACKUPS_MANAGE]}><BackupsPage /></Guard>} />
          <Route path="/reports" element={<Guard perms={[PERM.REPORTS_ALL, PERM.REPORTS_INVENTORY, PERM.REPORTS_OWN_SALES]}><ReportsPage /></Guard>} />
          <Route path="/finance" element={<Guard perms={[PERM.FINANCE_READ]}><FinancePage /></Guard>} />
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
          <Route path="*" element={<NotFoundPage />} />
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
