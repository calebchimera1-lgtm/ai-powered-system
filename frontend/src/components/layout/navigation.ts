import {
  ArrowLeftRight,
  Bell,
  ShieldAlert,
  TrendingUp,
  ShoppingBasket,
  ClipboardList,
  ClipboardCheck,
  LineChart,
  PackageCheck,
  Receipt,
  ScanLine,
  RotateCcw,
  ShoppingCart,
  Wallet,
  FolderTree,
  History,
  Home,
  Package,
  Truck,
  UserCircle,
  Users,
  type LucideIcon,
} from 'lucide-react';

import { PERM, type PermissionCode } from '@/auth/permissions';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** User needs at least one of these. Empty = everyone signed in. */
  anyOf: PermissionCode[];
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

// Modules are added here as each phase is delivered.
export const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Overview',
    items: [{ to: '/', label: 'Home', icon: Home, anyOf: [] }],
  },
  {
    title: 'Sales',
    items: [
      { to: '/pos', label: 'Point of sale', icon: ShoppingCart, anyOf: [PERM.SALES_CREATE] },
      { to: '/sales', label: 'Sales', icon: Receipt, anyOf: [PERM.SALES_READ_OWN, PERM.SALES_READ_ALL] },
      { to: '/returns', label: 'Returns', icon: RotateCcw, anyOf: [PERM.RETURNS_REQUEST, PERM.RETURNS_APPROVE] },
    ],
  },
  {
    title: 'Inventory',
    items: [
      { to: '/products', label: 'Products', icon: Package, anyOf: [PERM.PRODUCTS_READ] },
      { to: '/categories', label: 'Categories', icon: FolderTree, anyOf: [PERM.PRODUCTS_WRITE] },
      { to: '/stock/movements', label: 'Stock movements', icon: ArrowLeftRight, anyOf: [PERM.STOCK_READ] },
      { to: '/stock/adjustments', label: 'Adjustments', icon: ClipboardCheck, anyOf: [PERM.STOCK_READ] },
    ],
  },
  {
    title: 'Purchasing',
    items: [
      { to: '/suppliers', label: 'Suppliers', icon: Truck, anyOf: [PERM.SUPPLIERS_READ] },
      { to: '/purchasing/orders', label: 'Purchase orders', icon: ClipboardList, anyOf: [PERM.PURCHASES_READ] },
      { to: '/purchasing/receipts', label: 'Goods received', icon: PackageCheck, anyOf: [PERM.PURCHASES_READ] },
      { to: '/purchasing/invoices', label: 'Scan invoices', icon: ScanLine, anyOf: [PERM.INVOICES_UPLOAD, PERM.INVOICES_APPROVE] },
    ],
  },
  {
    title: 'Insights',
    items: [
      { to: '/forecasts', label: 'Demand forecast', icon: TrendingUp, anyOf: [PERM.FORECASTS_READ] },
      { to: '/reorder', label: 'Reorder suggestions', icon: ShoppingBasket, anyOf: [PERM.PURCHASES_WRITE] },
      { to: '/anomalies', label: 'Irregularities', icon: ShieldAlert, anyOf: [PERM.ANOMALIES_READ] },
    ],
  },
  {
    title: 'Finance',
    items: [
      { to: '/finance', label: 'Profit and sales', icon: LineChart, anyOf: [PERM.FINANCE_READ] },
      { to: '/expenses', label: 'Expenses', icon: Wallet, anyOf: [PERM.FINANCE_READ] },
    ],
  },
  {
    title: 'Administration',
    items: [
      { to: '/users', label: 'Users', icon: Users, anyOf: [PERM.USERS_READ] },
      { to: '/audit-log', label: 'Audit log', icon: History, anyOf: [PERM.AUDIT_READ] },
    ],
  },
  {
    title: 'Account',
    items: [
      { to: '/notifications', label: 'Notifications', icon: Bell, anyOf: [] },
      { to: '/account', label: 'My account', icon: UserCircle, anyOf: [] },
    ],
  },
];

export function visibleSections(canAny: (...p: PermissionCode[]) => boolean): NavSection[] {
  return NAV_SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((i) => i.anyOf.length === 0 || canAny(...i.anyOf)),
  })).filter((s) => s.items.length > 0);
}
