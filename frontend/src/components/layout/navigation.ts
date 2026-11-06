import {
  ArrowLeftRight,
  ClipboardCheck,
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
    items: [{ to: '/suppliers', label: 'Suppliers', icon: Truck, anyOf: [PERM.SUPPLIERS_READ] }],
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
    items: [{ to: '/account', label: 'My account', icon: UserCircle, anyOf: [] }],
  },
];

export function visibleSections(canAny: (...p: PermissionCode[]) => boolean): NavSection[] {
  return NAV_SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((i) => i.anyOf.length === 0 || canAny(...i.anyOf)),
  })).filter((s) => s.items.length > 0);
}
